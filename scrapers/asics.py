"""
ASICS scraper.

Strategy: Fetch the ASICS US sale page and parse product JSON from the HTML.
ASICS embeds product data in <script type="application/ld+json"> blocks
and sometimes in window.__INITIAL_STATE__.

Shoe sizes checked: US 12 / EU 45-46.
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import match_shoe_size
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

SALE_URL = "https://www.asics.com/us/en-us/sale/"


class AsicsScraper(BaseScraper):
    brand_name    = "Asics"
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

        discounts: list[float] = []
        sizes: set[str] = set()

        # Parse JSON-LD product listings
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                ld = json.loads(script.string or "")
                d, s = self._parse_ld(ld)
                discounts.extend(d)
                sizes.update(s)
            except Exception:
                pass

        # Try window.__INITIAL_STATE__ / __NEXT_DATA__
        for script in soup.find_all("script"):
            text = script.string or ""
            for pattern in [
                r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\});',
                r'window\.__STATE__\s*=\s*(\{.+?\});',
            ]:
                m = re.search(pattern, text, re.DOTALL)
                if m:
                    try:
                        state = json.loads(m.group(1))
                        d, s = self._parse_state(state)
                        discounts.extend(d)
                        sizes.update(s)
                    except Exception:
                        pass

        # HTML fallback
        if not discounts:
            pcts = re.findall(r'(\d{2,3})\s*%\s*off', resp.text, re.I)
            if pcts:
                max_d = max(int(p) for p in pcts)
                if max_d >= SALE_THRESHOLD_PCT:
                    return SaleInfo(
                        brand=self.brand_name, is_on_sale=True,
                        sale_type="percent-off", discount_pct=max_d,
                        sale_url=SALE_URL, sizes_available=[],
                    )
            return _no_sale(self.brand_name, SALE_URL)

        max_d = max(discounts)
        if max_d < SALE_THRESHOLD_PCT:
            return _no_sale(self.brand_name, SALE_URL)

        return SaleInfo(
            brand=self.brand_name, is_on_sale=True,
            sale_type="clearance" if max_d >= 50 else "percent-off",
            discount_pct=round(max_d), sale_url=SALE_URL,
            sizes_available=sorted(sizes),
        )

    def _parse_ld(self, ld) -> tuple[list[float], set[str]]:
        discounts: list[float] = []
        sizes: set[str] = set()
        items = []

        if isinstance(ld, list):
            items = ld
        elif isinstance(ld, dict):
            if ld.get("@type") in ("Product", "ProductGroup"):
                items = [ld]
            else:
                items = ld.get("itemListElement", [])

        for item in items:
            thing = item.get("item", item) if isinstance(item, dict) else item
            offers = thing.get("offers", {}) if isinstance(thing, dict) else {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            price     = _to_float(offers.get("price"))
            high      = _to_float(offers.get("highPrice"))
            list_p    = _to_float(offers.get("priceCurrency"))

            # Try priceSpecification
            spec = offers.get("priceSpecification", [])
            if isinstance(spec, list):
                for s in spec:
                    if "Original" in str(s.get("name", "")):
                        high = _to_float(s.get("price")) or high

            if price and high and high > price:
                discounts.append((high - price) / high * 100)

            # Check sizes from product description or name
            for key in ("name", "description"):
                text = str(thing.get(key, "") or "")
                r = match_shoe_size(text)
                if r: sizes.add(r)

        return discounts, sizes

    def _parse_state(self, state: dict) -> tuple[list[float], set[str]]:
        discounts: list[float] = []
        sizes: set[str] = set()
        products = _deep_find_list(state, "products") or []
        for p in products:
            orig = _to_float(p.get("originalPrice") or p.get("listPrice"))
            curr = _to_float(p.get("price") or p.get("salePrice"))
            if orig and curr and orig > curr:
                discounts.append((orig - curr) / orig * 100)
            for v in p.get("variants", []) or []:
                sz = str(v.get("size") or "")
                r = match_shoe_size(sz)
                if r: sizes.add(r)
        return discounts, sizes


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
