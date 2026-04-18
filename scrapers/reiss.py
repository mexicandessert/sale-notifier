"""
Reiss scraper.

Strategy: Fetch the Reiss sale page and extract product/discount data.
Reiss uses a Next.js front-end; product data is often embedded in
__NEXT_DATA__ or a window.__INITIAL_STATE__ script tag.
Falls back to scanning the HTML for percentage-off patterns.
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import match_top_size, match_bottom_inch_size, match_bottom_alpha_size
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

SALE_URL = "https://www.reiss.com/sale/"


class ReissScraper(BaseScraper):
    brand_name    = "Reiss"
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

        # ── Try __NEXT_DATA__ ─────────────────────────────────────────
        tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if tag and tag.string:
            result = self._parse_next_data(tag.string, resp.text)
            if result is not None:
                return result

        # ── Fallback: percentage patterns in HTML ─────────────────────
        return self._html_fallback(soup, resp.text)

    # ------------------------------------------------------------------

    def _parse_next_data(self, raw: str, full_html: str) -> SaleInfo | None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

        # Reiss stores products under pageProps → initialData → products
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
            orig = _coerce_float(
                p.get("originalPrice") or p.get("fullPrice") or p.get("rrp")
            )
            curr = _coerce_float(
                p.get("salePrice") or p.get("currentPrice") or p.get("price")
            )
            if orig and curr and orig > curr > 0:
                discounts.append((orig - curr) / orig * 100)

            # Variant / size data
            for variant in p.get("variants", []) or p.get("sizes", []):
                for sz in _extract_size_strings(variant):
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
            # Sale page exists but no discount data parsed — treat as sale with unknown %
            site_wide = _detect_site_wide(full_html)
            return SaleInfo(
                brand=self.brand_name,
                is_on_sale=True,
                sale_type="site-wide" if site_wide else "sale",
                discount_pct=None,
                sale_url=SALE_URL,
                sizes_available=sorted(sizes_found),
                has_long_option=has_long,
            )

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

    def _html_fallback(self, soup: BeautifulSoup, raw_html: str) -> SaleInfo:
        # Check the page actually has sale content (not just a redirect)
        page_text = soup.get_text(" ", strip=True)
        has_sale_content = bool(
            re.search(r'\bsale\b|\bdiscount\b|\breduced\b', page_text, re.I)
        )
        if not has_sale_content:
            return self._no_sale()

        pct_matches = re.findall(r'(\d{2,3})\s*%\s*off', raw_html, re.IGNORECASE)
        if not pct_matches:
            # Page has sale section but we can't confirm discount level
            site_wide = _detect_site_wide(raw_html)
            if site_wide:
                return SaleInfo(
                    brand=self.brand_name,
                    is_on_sale=True,
                    sale_type="site-wide",
                    discount_pct=None,
                    sale_url=SALE_URL,
                )
            return self._no_sale("Sale page found but discount % not detectable")

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
        r'site.?wide|up\s+to\s+\d+%\s+off\s+everything|extra\s+\d+%\s+off',
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
        return float(str(val).replace("$", "").replace("£", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _extract_size_strings(variant: dict) -> list[str]:
    out = []
    for key in ("size", "sizeLabel", "value", "label", "name", "title"):
        v = variant.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    return out
