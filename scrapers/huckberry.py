"""
Huckberry scraper.

Huckberry is a multi-brand outdoor/lifestyle retailer.
We monitor their sale section broadly rather than brand-by-brand.

Strategy:
  1. Fetch the Huckberry sale/clearance page
  2. Detect discounted products and their discount %
  3. Check size availability across all sale items (tops, bottoms, shoes)

Note: Huckberry uses a custom React/Next.js frontend. Product data is
often embedded in __NEXT_DATA__ or via their internal API.
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import (
    match_top_size, match_bottom_inch_size,
    match_bottom_alpha_size, match_shoe_size,
)
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

SALE_URL = "https://huckberry.com/store/sale"


class HuckberryScraper(BaseScraper):
    brand_name    = "Huckberry"
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
            result = self._parse_next_data(tag.string)
            if result is not None:
                return result

        # ── Try JSON-LD ───────────────────────────────────────────────
        result = self._parse_json_ld(soup)
        if result is not None:
            return result

        # ── Fallback: HTML analysis ───────────────────────────────────
        return self._html_fallback(soup, resp.text)

    # ------------------------------------------------------------------

    def _parse_next_data(self, raw: str) -> SaleInfo | None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

        products = (
            _deep_find_list(data, "products")
            or _deep_find_list(data, "items")
            or _deep_find_list(data, "results")
            or []
        )
        if not products:
            return None

        discounts: list[float] = []
        sizes_found: set[str] = set()
        has_long = False

        for p in products:
            orig = _coerce_float(
                p.get("originalPrice") or p.get("compareAtPrice")
                or p.get("retail_price") or p.get("listPrice")
            )
            curr = _coerce_float(
                p.get("salePrice") or p.get("price") or p.get("currentPrice")
            )
            if orig and curr and orig > curr > 0:
                discounts.append((orig - curr) / orig * 100)

            for variant in (p.get("variants") or p.get("sizes") or []):
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
                    r = match_shoe_size(sz)
                    if r:
                        sizes_found.add(r)

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

    def _parse_json_ld(self, soup: BeautifulSoup) -> SaleInfo | None:
        discounts: list[float] = []
        sizes_found: set[str] = set()

        for tag in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(tag.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") != "Product":
                    continue
                offers = item.get("offers", {})
                if isinstance(offers, dict):
                    offers = [offers]
                for offer in offers:
                    high = _coerce_float(offer.get("highPrice") or offer.get("price"))
                    low  = _coerce_float(offer.get("lowPrice"))
                    if high and low and high > low > 0:
                        discounts.append((high - low) / high * 100)

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
        )

    def _html_fallback(self, soup: BeautifulSoup, raw_html: str) -> SaleInfo:
        page_text = soup.get_text(" ", strip=True)
        has_sale = bool(re.search(r'\bsale\b|\bsave\b|\boff\b|\bdeal', page_text, re.I))
        if not has_sale:
            return self._no_sale()

        pct_matches = re.findall(r'(\d{2,3})\s*%\s*off', raw_html, re.IGNORECASE)
        if not pct_matches:
            # Look for strikethrough prices as signal
            has_strikethrough = bool(
                soup.find_all(["s", "del"])
                or soup.find_all(class_=re.compile(r'compare|original|was|strike', re.I))
            )
            if has_strikethrough:
                return SaleInfo(
                    brand=self.brand_name,
                    is_on_sale=True,
                    sale_type="sale",
                    discount_pct=None,
                    sale_url=SALE_URL,
                )
            return self._no_sale("Sale section found but discount % not detectable")

        max_disc = max(int(p) for p in pct_matches)
        if max_disc < SALE_THRESHOLD_PCT:
            return self._no_sale(f"Max discount {max_disc}% below threshold")

        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=True,
            sale_type="clearance" if max_disc >= 50 else "percent-off",
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


def _extract_size_strings(variant: dict) -> list[str]:
    out = []
    for key in ("size", "sizeLabel", "value", "label", "name", "title"):
        v = variant.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    return out
