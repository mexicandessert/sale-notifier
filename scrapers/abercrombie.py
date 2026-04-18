"""
Abercrombie & Fitch scraper.

Strategy:
  1. Fetch the ANF sale page HTML; parse embedded JSON-LD or __NEXT_DATA__.
  2. Look for percentage-off patterns in the raw HTML as a fallback.
  3. Abercrombie also has a clearance section at /shop/us/clearance.
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import match_top_size, match_bottom_inch_size, match_bottom_alpha_size
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

SALE_URL = "https://www.abercrombie.com/shop/us/mens-sale"


class AbercrombieScraper(BaseScraper):
    brand_name    = "Abercrombie"
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
            "Referer": "https://www.abercrombie.com/",
        }
        resp = requests.get(SALE_URL, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Try __NEXT_DATA__
        next_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_tag and next_tag.string:
            try:
                data = json.loads(next_tag.string)
                result = self._parse_products(data, resp.text)
                if result.is_on_sale:
                    return result
            except Exception:
                pass

        # Try application/ld+json blocks
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                ld = json.loads(script.string or "")
                result = self._parse_ld(ld)
                if result.is_on_sale:
                    return result
            except Exception:
                pass

        return self._html_fallback(resp.text)

    def _parse_products(self, data: dict, raw_html: str) -> SaleInfo:
        products = _deep_find_list(data, "products") or _deep_find_list(data, "items") or []
        discounts: list[float] = []
        sizes: set[str] = set()
        has_long = False

        for p in products:
            orig = _to_float(p.get("listPrice") or p.get("originalPrice"))
            curr = _to_float(p.get("salePrice") or p.get("currentPrice"))
            if orig and curr and orig > curr:
                discounts.append((orig - curr) / orig * 100)
            for v in p.get("variants", []) or []:
                sz = str(v.get("size") or "")
                if sz:
                    r = match_top_size(sz); sizes.add(r) if r else None
                    r, l = match_bottom_inch_size(sz)
                    if r: sizes.add(r); has_long |= l
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

    def _parse_ld(self, ld) -> SaleInfo:
        # ItemList of products with offers
        items = ld.get("itemListElement", []) if isinstance(ld, dict) else []
        discounts: list[float] = []
        for item in items:
            thing = item.get("item", item)
            offers = thing.get("offers", {})
            price = _to_float(offers.get("price"))
            high  = _to_float(offers.get("highPrice") or offers.get("priceSpecification", {}).get("price"))
            if price and high and high > price:
                discounts.append((high - price) / high * 100)
        if not discounts:
            return _no_sale(self.brand_name, SALE_URL)
        max_d = max(discounts)
        if max_d < SALE_THRESHOLD_PCT:
            return _no_sale(self.brand_name, SALE_URL)
        return SaleInfo(
            brand=self.brand_name, is_on_sale=True,
            sale_type="percent-off", discount_pct=round(max_d), sale_url=SALE_URL,
        )

    def _html_fallback(self, raw: str) -> SaleInfo:
        pcts = re.findall(r'(\d{2,3})\s*%\s*off', raw, re.I)
        if not pcts:
            return _no_sale(self.brand_name, SALE_URL)
        max_d = max(int(p) for p in pcts)
        if max_d < SALE_THRESHOLD_PCT:
            return _no_sale(self.brand_name, SALE_URL)
        site_wide = bool(re.search(r'site.?wide|everything\s+on\s+sale', raw, re.I))
        return SaleInfo(
            brand=self.brand_name, is_on_sale=True,
            sale_type="site-wide" if site_wide else "percent-off",
            discount_pct=max_d, sale_url=SALE_URL, sizes_available=[],
        )


def _no_sale(brand, url):
    return SaleInfo(brand=brand, is_on_sale=False, sale_type="none",
                    discount_pct=None, sale_url=url)

def _to_float(val):
    if val is None: return None
    try: return float(str(val).replace('$','').replace(',','').strip())
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
