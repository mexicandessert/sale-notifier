"""
Madewell scraper.

Strategy: Fetch Madewell's sale page and extract product/discount data
from the embedded __NEXT_DATA__ JSON or percentage-off text patterns.
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import match_top_size, match_bottom_inch_size, match_bottom_alpha_size
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

SALE_URL = "https://www.madewell.com/s/sale"


class MadewellScraper(BaseScraper):
    brand_name    = "Madewell"
    sale_url      = SALE_URL
    low_frequency = False

    def check_sale(self) -> SaleInfo:
        try:
            return self._scrape()
        except Exception as exc:
            return self.make_error_result(str(exc))

    def _scrape(self) -> SaleInfo:
        resp = requests.get(SALE_URL, headers=self.HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        next_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_tag and next_tag.string:
            try:
                data = json.loads(next_tag.string)
                return self._parse_next_data(data, resp.text)
            except json.JSONDecodeError:
                pass

        return self._parse_html_fallback(resp.text)

    def _parse_next_data(self, data: dict, raw_html: str) -> SaleInfo:
        products = _deep_find_list(data, "products") or _deep_find_list(data, "items") or []

        discounts: list[float] = []
        sizes_found: set[str] = set()
        has_long = False

        for product in products:
            orig = _to_float(product.get("originalPrice") or product.get("listPrice"))
            curr = _to_float(product.get("salePrice") or product.get("currentPrice"))
            if orig and curr and orig > curr:
                discounts.append((orig - curr) / orig * 100)

            for variant in product.get("variants", []) or []:
                sz = variant.get("size") or variant.get("label") or ""
                if sz:
                    _collect_sizes(sz, sizes_found, lambda: None)
                    r, l = match_bottom_inch_size(sz)
                    if r:
                        sizes_found.add(r)
                        if l: has_long = True
                    r, l = match_bottom_alpha_size(sz)
                    if r:
                        sizes_found.add(r)
                        if l: has_long = True
                    r = match_top_size(sz)
                    if r: sizes_found.add(r)

        if not discounts:
            # Fallback to regex scan
            return self._parse_html_fallback(raw_html)

        max_disc = max(discounts)
        if max_disc < SALE_THRESHOLD_PCT:
            return _no_sale(self.brand_name, SALE_URL)

        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=True,
            sale_type="clearance" if max_disc >= 50 else "percent-off",
            discount_pct=round(max_disc),
            sale_url=SALE_URL,
            sizes_available=sorted(sizes_found),
            has_long_option=has_long,
        )

    def _parse_html_fallback(self, raw_html: str) -> SaleInfo:
        pct_matches = re.findall(r'(\d{2,3})\s*%\s*off', raw_html, re.IGNORECASE)
        if not pct_matches:
            return _no_sale(self.brand_name, SALE_URL)
        max_disc = max(int(p) for p in pct_matches)
        if max_disc < SALE_THRESHOLD_PCT:
            return _no_sale(self.brand_name, SALE_URL)
        site_wide = bool(re.search(r'site.?wide|everything\s+on\s+sale', raw_html, re.I))
        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=True,
            sale_type="site-wide" if site_wide else "percent-off",
            discount_pct=max_disc,
            sale_url=SALE_URL,
            sizes_available=[],
        )


# ---------------------------------------------------------------------------
# Helpers shared across Gap-family scrapers
# ---------------------------------------------------------------------------

def _no_sale(brand: str, url: str) -> SaleInfo:
    return SaleInfo(brand=brand, is_on_sale=False, sale_type="none",
                    discount_pct=None, sale_url=url)


def _to_float(val) -> float | None:
    if val is None: return None
    try:
        return float(str(val).replace('$', '').replace(',', '').strip())
    except (ValueError, TypeError):
        return None


def _deep_find_list(obj, key: str) -> list | None:
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], list):
            return obj[key]
        for v in obj.values():
            r = _deep_find_list(v, key)
            if r is not None: return r
    elif isinstance(obj, list):
        for item in obj:
            r = _deep_find_list(item, key)
            if r is not None: return r
    return None


def _collect_sizes(sz: str, sizes_found: set, _unused) -> None:
    r = match_top_size(sz)
    if r: sizes_found.add(r)
