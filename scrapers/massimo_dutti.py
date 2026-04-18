"""
Massimo Dutti scraper.

Massimo Dutti (Inditex) runs seasonal sales. Their site embeds product data
in window.__INITIAL_PROPS__ or similar patterns.

Sale page: https://www.massimodutti.com/en/sale
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import match_top_size, match_bottom_alpha_size
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

SALE_URL = "https://www.massimodutti.com/en/sale"


class MassimoDuttiScraper(BaseScraper):
    brand_name    = "Massimo Dutti"
    sale_url      = SALE_URL
    low_frequency = False

    def check_sale(self) -> SaleInfo:
        try:
            return self._scrape()
        except Exception as exc:
            return self.make_error_result(str(exc))

    def _scrape(self) -> SaleInfo:
        headers = {
            **self.HEADERS,
            "Referer": "https://www.massimodutti.com/en/",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.get(SALE_URL, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Try Inditex's embedded JSON patterns
        for script in soup.find_all("script"):
            text = script.string or ""
            for pat in [
                r'window\.__INITIAL_PROPS__\s*=\s*(\{.+?\})\s*;',
                r'window\.__REDUX_STATE__\s*=\s*(\{.+?\})\s*;',
            ]:
                m = re.search(pat, text, re.DOTALL)
                if m:
                    try:
                        state = json.loads(m.group(1))
                        result = self._parse_state(state)
                        if result.is_on_sale:
                            return result
                    except Exception:
                        pass

        # __NEXT_DATA__
        next_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_tag and next_tag.string:
            try:
                data = json.loads(next_tag.string)
                result = self._parse_state(data)
                if result.is_on_sale:
                    return result
            except Exception:
                pass

        return self._html_fallback(resp.text, soup)

    def _parse_state(self, data: dict) -> SaleInfo:
        products = (
            _deep_find_list(data, "products") or
            _deep_find_list(data, "items") or
            _deep_find_list(data, "productList") or []
        )
        discounts: list[float] = []
        sizes: set[str] = set()
        has_long = False

        for p in products:
            orig = _to_float(p.get("originalPrice") or p.get("regularPrice"))
            curr = _to_float(p.get("price") or p.get("currentPrice"))
            if orig and curr and orig > curr:
                discounts.append((orig - curr) / orig * 100)
            for v in p.get("variants", []) or p.get("sizes", []) or []:
                sz = str(v.get("name") or v.get("label") or v.get("value") or "")
                r = match_top_size(sz); sizes.add(r) if r else None
                r, l = match_bottom_alpha_size(sz)
                if r: sizes.add(r); has_long |= l

        if not discounts:
            return _no_sale(self.brand_name, SALE_URL)
        max_d = max(discounts)
        if max_d < SALE_THRESHOLD_PCT:
            return _no_sale(self.brand_name, SALE_URL)

        return SaleInfo(
            brand=self.brand_name, is_on_sale=True,
            sale_type="clearance" if max_d >= 50 else "percent-off",
            discount_pct=round(max_d), sale_url=SALE_URL,
            sizes_available=sorted(sizes), has_long_option=has_long,
        )

    def _html_fallback(self, raw: str, soup: BeautifulSoup) -> SaleInfo:
        # Massimo Dutti sale pages clearly show "SALE" in nav when active
        sale_nav = soup.find(string=re.compile(r'\bsale\b', re.I))
        pcts = re.findall(r'(\d{2,3})\s*%\s*(?:off|discount)', raw, re.I)

        if not pcts and not sale_nav:
            return _no_sale(self.brand_name, SALE_URL)

        if pcts:
            max_d = max(int(p) for p in pcts)
            if max_d >= SALE_THRESHOLD_PCT:
                return SaleInfo(
                    brand=self.brand_name, is_on_sale=True,
                    sale_type="percent-off", discount_pct=max_d,
                    sale_url=SALE_URL, sizes_available=[],
                )

        # Sale section exists but discount % not readable
        return SaleInfo(
            brand=self.brand_name, is_on_sale=True,
            sale_type="sale", discount_pct=None, sale_url=SALE_URL,
            sizes_available=[],
            error="Sale detected — verify discount % on site",
        )


def _no_sale(brand, url):
    return SaleInfo(brand=brand, is_on_sale=False, sale_type="none",
                    discount_pct=None, sale_url=url)

def _to_float(val):
    if val is None: return None
    try: return float(str(val).replace('$','').replace(',','').replace('€','').strip())
    except: return None

def _deep_find_list(obj, key):
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], list): return obj[key]
        for v in obj.values():
            r = _deep_find_list(v, key)
            if r is not None: return r
    elif isinstance(obj, list):
        for item in obj:
            r = _deep_find_list(item, key)
            if r is not None: return r
    return None
