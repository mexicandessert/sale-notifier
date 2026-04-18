"""
J.Crew scraper.

Strategy: Fetch J.Crew sale page, parse __NEXT_DATA__ JSON or HTML patterns.
J.Crew runs frequent promotions (extra % off sale, friends & family, etc.).
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import match_top_size, match_bottom_inch_size, match_bottom_alpha_size
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

SALE_URL = "https://www.jcrew.com/sale"


class JCrewScraper(BaseScraper):
    brand_name    = "J.Crew"
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
                result = self._parse_next_data(data)
                if result.is_on_sale:
                    return result
            except (json.JSONDecodeError, Exception):
                pass

        return self._parse_html(resp.text)

    def _parse_next_data(self, data: dict) -> SaleInfo:
        products = _deep_find_list(data, "products") or _deep_find_list(data, "items") or []

        discounts: list[float] = []
        sizes_found: set[str] = set()
        has_long = False

        for p in products:
            orig = _to_float(p.get("originalPrice") or p.get("regularPrice"))
            sale = _to_float(p.get("salePrice") or p.get("currentPrice"))
            if orig and sale and orig > sale:
                discounts.append((orig - sale) / orig * 100)

            for v in p.get("variants", []) or []:
                sz = str(v.get("size") or v.get("value") or "")
                if sz:
                    r = match_top_size(sz)
                    if r: sizes_found.add(r)
                    r, l = match_bottom_inch_size(sz)
                    if r:
                        sizes_found.add(r)
                        if l: has_long = True
                    r, l = match_bottom_alpha_size(sz)
                    if r:
                        sizes_found.add(r)
                        if l: has_long = True

        if not discounts:
            return _no_sale(self.brand_name, SALE_URL)

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

    def _parse_html(self, raw: str) -> SaleInfo:
        pcts = re.findall(r'(\d{2,3})\s*%\s*off', raw, re.IGNORECASE)
        if not pcts:
            return _no_sale(self.brand_name, SALE_URL)
        max_disc = max(int(p) for p in pcts)
        if max_disc < SALE_THRESHOLD_PCT:
            return _no_sale(self.brand_name, SALE_URL)
        site_wide = bool(re.search(r'site.?wide|everything|all\s+styles', raw, re.I))
        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=True,
            sale_type="site-wide" if site_wide else "percent-off",
            discount_pct=max_disc,
            sale_url=SALE_URL,
            sizes_available=[],
        )


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
