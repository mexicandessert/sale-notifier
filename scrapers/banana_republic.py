"""
Banana Republic scraper.

Strategy: Fetch the BR sale page and look for discounted products.
BR renders product data as JSON inside a <script id="__NEXT_DATA__"> tag.
Falls back to HTML analysis if that pattern is absent.
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import match_top_size, match_bottom_inch_size, match_bottom_alpha_size
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT


SALE_URL = "https://bananarepublic.gap.com/browse/sale.do"


class BananaRepublicScraper(BaseScraper):
    brand_name  = "Banana Republic"
    sale_url    = SALE_URL
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

        # ── Try __NEXT_DATA__ (Next.js embedded JSON) ─────────────────
        next_data_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_data_tag and next_data_tag.string:
            return self._parse_next_data(next_data_tag.string)

        # ── Fallback: look for sale indicators in HTML ─────────────────
        return self._parse_html_fallback(soup, resp.text)

    # ------------------------------------------------------------------

    def _parse_next_data(self, raw: str) -> SaleInfo:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._no_sale("Could not parse __NEXT_DATA__")

        # Walk the Next.js page props to find product listings
        products = _deep_find_list(data, "products") or _deep_find_list(data, "productList") or []

        discounts: list[float] = []
        sizes_found: set[str] = set()
        has_long = False

        for product in products:
            original = _coerce_float(product.get("originalPrice") or product.get("listPrice"))
            current  = _coerce_float(product.get("currentPrice") or product.get("salePrice"))
            if original and current and original > current:
                pct = (original - current) / original * 100
                discounts.append(pct)

            # Size checking from swatches / variants
            for variant in product.get("variants", []) or product.get("swatches", []):
                for size_val in _extract_sizes(variant):
                    r = match_top_size(size_val)
                    if r: sizes_found.add(r)
                    r, l = match_bottom_inch_size(size_val)
                    if r:
                        sizes_found.add(r)
                        if l: has_long = True
                    r, l = match_bottom_alpha_size(size_val)
                    if r:
                        sizes_found.add(r)
                        if l: has_long = True

        if not discounts:
            return self._no_sale()

        max_disc = max(discounts)
        if max_disc < SALE_THRESHOLD_PCT:
            return self._no_sale(f"Max discount {max_disc:.0f}% below threshold")

        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=True,
            sale_type="clearance" if max_disc >= 50 else "percent-off",
            discount_pct=round(max_disc),
            sale_url=SALE_URL,
            sizes_available=sorted(sizes_found),
            has_long_option=has_long,
        )

    def _parse_html_fallback(self, soup: BeautifulSoup, raw_html: str) -> SaleInfo:
        # Look for percentage-off text patterns in the page
        pct_matches = re.findall(r'(\d{2,3})\s*%\s*off', raw_html, re.IGNORECASE)
        if not pct_matches:
            return self._no_sale()

        max_disc = max(int(p) for p in pct_matches)
        if max_disc < SALE_THRESHOLD_PCT:
            return self._no_sale(f"Max discount {max_disc}% below threshold")

        # Check for site-wide indicator
        site_wide = bool(re.search(r'site.?wide|everything\s+on\s+sale|all\s+styles', raw_html, re.IGNORECASE))
        sale_type = "site-wide" if site_wide else ("clearance" if max_disc >= 50 else "percent-off")

        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=True,
            sale_type=sale_type,
            discount_pct=max_disc,
            sale_url=SALE_URL,
            sizes_available=[],   # Can't reliably check sizes from fallback
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
    """Recursively search a nested dict/list for the first list value at `key`."""
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], list):
            return obj[key]
        for v in obj.values():
            result = _deep_find_list(v, key)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _deep_find_list(item, key)
            if result is not None:
                return result
    return None


def _coerce_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace('$', '').replace(',', '').strip())
    except (ValueError, TypeError):
        return None


def _extract_sizes(variant: dict) -> list[str]:
    sizes = []
    for key in ("size", "sizeLabel", "value", "label", "name"):
        v = variant.get(key)
        if isinstance(v, str) and v:
            sizes.append(v)
    return sizes
