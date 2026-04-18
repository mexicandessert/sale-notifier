"""
Levi's scraper.

Strategy: Fetch the Levi's US sale page and extract discount data.
Levi's renders product tiles server-side with structured data in
JSON-LD or embedded script tags. Falls back to % pattern scanning.
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import match_top_size, match_bottom_inch_size, match_bottom_alpha_size
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

SALE_URL = "https://www.levi.com/US/en_US/sale"


class LevisScraper(BaseScraper):
    brand_name    = "Levi's"
    sale_url      = SALE_URL
    low_frequency = False

    def check_sale(self) -> SaleInfo:
        try:
            return self._scrape()
        except Exception as exc:
            return self.make_error_result(str(exc))

    def _scrape(self) -> SaleInfo:
        resp = requests.get(
            SALE_URL,
            headers={**self.HEADERS, "Accept": "text/html"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # ── Try JSON-LD product data ───────────────────────────────────
        json_ld_result = self._parse_json_ld(soup)
        if json_ld_result is not None:
            return json_ld_result

        # ── Try __NEXT_DATA__ / window.__STATE__ ──────────────────────
        next_data_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_data_tag and next_data_tag.string:
            result = self._parse_next_data(next_data_tag.string)
            if result is not None:
                return result

        # ── Fallback: scan HTML for price patterns ────────────────────
        return self._html_fallback(soup, resp.text)

    # ------------------------------------------------------------------

    def _parse_json_ld(self, soup: BeautifulSoup) -> SaleInfo | None:
        """Parse JSON-LD <script type="application/ld+json"> blocks."""
        discounts: list[float] = []
        sizes_found: set[str] = set()
        has_long = False

        for tag in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(tag.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") not in ("Product", "ItemList"):
                    continue
                offers = item.get("offers", {})
                if isinstance(offers, dict):
                    offers = [offers]
                for offer in offers:
                    high = _coerce_float(offer.get("highPrice") or offer.get("price"))
                    low  = _coerce_float(offer.get("lowPrice"))
                    if high and low and high > low > 0:
                        discounts.append((high - low) / high * 100)

                # Sizes from itemOffered
                for offered in item.get("itemOffered", []):
                    sz = offered.get("size") or offered.get("name", "")
                    if sz:
                        for fn in (match_top_size, ):
                            r = fn(sz)
                            if r:
                                sizes_found.add(r)
                        r, l = match_bottom_inch_size(sz)
                        if r:
                            sizes_found.add(r)
                            if l:
                                has_long = True
                        r, l = match_bottom_alpha_size(sz)
                        if r:
                            sizes_found.add(r)
                            if l:
                                has_long = True

        if not discounts:
            return None

        max_disc = max(discounts)
        if max_disc < SALE_THRESHOLD_PCT:
            return SaleInfo(
                brand=self.brand_name,
                is_on_sale=False,
                sale_type="below-threshold",
                discount_pct=round(max_disc),
                sale_url=SALE_URL,
            )

        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=True,
            sale_type="clearance" if max_disc >= 50 else "percent-off",
            discount_pct=round(max_disc),
            sale_url=SALE_URL,
            sizes_available=sorted(sizes_found),
            has_long_option=has_long,
        )

    def _parse_next_data(self, raw: str) -> SaleInfo | None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

        products = (
            _deep_find_list(data, "products")
            or _deep_find_list(data, "items")
            or []
        )
        if not products:
            return None

        discounts: list[float] = []
        sizes_found: set[str] = set()
        has_long = False

        for p in products:
            orig = _coerce_float(p.get("originalPrice") or p.get("listPrice"))
            curr = _coerce_float(p.get("salePrice") or p.get("currentPrice") or p.get("price"))
            if orig and curr and orig > curr > 0:
                discounts.append((orig - curr) / orig * 100)

            for variant in p.get("variants", []) or p.get("sizes", []):
                sz = variant.get("size") or variant.get("label") or variant.get("value") or ""
                if not sz:
                    continue
                r = match_top_size(sz)
                if r:
                    sizes_found.add(r)
                r, l = match_bottom_inch_size(sz)
                if r:
                    sizes_found.add(r)
                    if l:
                        has_long = True
                r, l = match_bottom_alpha_size(sz)
                if r:
                    sizes_found.add(r)
                    if l:
                        has_long = True

        if not discounts:
            return None

        max_disc = max(discounts)
        if max_disc < SALE_THRESHOLD_PCT:
            return None

        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=True,
            sale_type="clearance" if max_disc >= 50 else "percent-off",
            discount_pct=round(max_disc),
            sale_url=SALE_URL,
            sizes_available=sorted(sizes_found),
            has_long_option=has_long,
        )

    def _html_fallback(self, soup: BeautifulSoup, raw_html: str) -> SaleInfo:
        # Levi's sale page should always have content; if we got 0 products something's wrong
        page_text = soup.get_text(" ", strip=True)
        has_sale = bool(re.search(r'\bsale\b|\bsave\b|\boff\b', page_text, re.I))
        if not has_sale:
            return self._no_sale()

        pct_matches = re.findall(r'(\d{2,3})\s*%\s*off', raw_html, re.IGNORECASE)
        if not pct_matches:
            site_wide = _detect_site_wide(raw_html)
            if site_wide:
                return SaleInfo(
                    brand=self.brand_name,
                    is_on_sale=True,
                    sale_type="site-wide",
                    discount_pct=None,
                    sale_url=SALE_URL,
                )
            return self._no_sale("Sale page found but discount level unclear")

        max_disc = max(int(p) for p in pct_matches)
        if max_disc < SALE_THRESHOLD_PCT:
            return self._no_sale(f"Max discount {max_disc}% below threshold")

        site_wide = _detect_site_wide(raw_html)
        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=True,
            sale_type="site-wide" if site_wide else ("clearance" if max_disc >= 50 else "percent-off"),
            discount_pct=max_disc,
            sale_url=SALE_URL,
            sizes_available=[],
        )

    def _no_sale(self, reason: str = "") -> SaleInfo:
        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=False,
            sale_type="none",
            discount_pct=None,
            sale_url=SALE_URL,
            error=reason or None,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_site_wide(html: str) -> bool:
    return bool(re.search(
        r'site.?wide|up\s+to\s+\d+%\s+off\s+everything|all\s+styles?\s+on\s+sale',
        html, re.IGNORECASE
    ))


def _deep_find_list(obj, key: str) -> list | None:
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], list):
            return obj[key]
        for v in obj.values():
            r = _deep_find_list(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _deep_find_list(item, key)
            if r is not None:
                return r
    return None


def _coerce_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None
