"""
Lululemon scraper.

Strategy:
  1. Hit Lululemon's internal search/browse API (used by their web app).
  2. Fall back to HTML scraping of /c/sale if API returns nothing useful.

Lululemon marks items with "Was $X" pricing for sale items.
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import match_top_size, match_bottom_inch_size, match_bottom_alpha_size
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

SALE_URL = "https://www.lululemon.com/en-us/c/sale"

# Lululemon's internal product browse API
API_URL = (
    "https://www.lululemon.com/en-us/c/sale"
    "?prefn1=product-start-date&prefv1=all"
    "&format=page-element&start=0&sz=96"
)


class LululemonScraper(BaseScraper):
    brand_name    = "Lululemon"
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
            "X-Requested-With": "XMLHttpRequest",
        }

        # Try the AJAX endpoint first
        try:
            resp = requests.get(API_URL, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                result = self._parse_response(resp, SALE_URL)
                if result.is_on_sale:
                    return result
        except Exception:
            pass

        # Full page fallback
        resp = requests.get(SALE_URL, headers=self.HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return self._parse_response(resp, SALE_URL)

    def _parse_response(self, resp, url: str) -> SaleInfo:
        raw = resp.text
        soup = BeautifulSoup(raw, "lxml")

        # Try __NEXT_DATA__
        next_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_tag and next_tag.string:
            try:
                data = json.loads(next_tag.string)
                result = self._parse_product_data(data, url)
                if result.is_on_sale:
                    return result
            except Exception:
                pass

        # Look for "Was $X Now $Y" pricing patterns
        was_now = re.findall(
            r'was\s*\$?\s*([\d.]+).*?now\s*\$?\s*([\d.]+)',
            raw, re.I | re.DOTALL
        )
        discounts: list[float] = []
        for was_str, now_str in was_now[:50]:  # limit iterations
            try:
                was, now = float(was_str), float(now_str)
                if was > now > 0:
                    discounts.append((was - now) / was * 100)
            except ValueError:
                pass

        # Also scan for % off
        pcts = re.findall(r'(\d{2,3})\s*%\s*off', raw, re.I)
        if pcts:
            discounts.extend(float(p) for p in pcts)

        if not discounts:
            # Check if sale page simply has products (no pricing in HTML)
            product_cards = soup.select('[data-testid="product-card"], .product-card, .product-tile')
            if len(product_cards) > 5:
                return SaleInfo(
                    brand=self.brand_name, is_on_sale=True,
                    sale_type="sale", discount_pct=None, sale_url=url,
                    sizes_available=[],
                    error="Sale detected but discount % not parseable — check site",
                )
            return _no_sale(self.brand_name, url)

        max_d = max(discounts)
        if max_d < SALE_THRESHOLD_PCT:
            return _no_sale(self.brand_name, url)

        # Size extraction from product tiles
        sizes: set[str] = set()
        has_long = False
        for el in soup.select('[data-size], [aria-label*="Size"], .size-chip'):
            sz = el.get("data-size") or el.get("aria-label") or el.text.strip()
            r = match_top_size(sz); sizes.add(r) if r else None
            r, l = match_bottom_alpha_size(sz)
            if r: sizes.add(r); has_long |= l
            r, l = match_bottom_inch_size(sz)
            if r: sizes.add(r); has_long |= l

        return SaleInfo(
            brand=self.brand_name, is_on_sale=True,
            sale_type="clearance" if max_d >= 50 else "percent-off",
            discount_pct=round(max_d), sale_url=url,
            sizes_available=sorted(sizes), has_long_option=has_long,
        )

    def _parse_product_data(self, data: dict, url: str) -> SaleInfo:
        products = _deep_find_list(data, "products") or _deep_find_list(data, "hits") or []
        discounts: list[float] = []
        sizes: set[str] = set()
        has_long = False
        for p in products:
            orig = _to_float(p.get("originalPrice") or p.get("listPrice"))
            curr = _to_float(p.get("price") or p.get("salePrice"))
            if orig and curr and orig > curr:
                discounts.append((orig - curr) / orig * 100)
            for v in p.get("variants", []) or []:
                sz = str(v.get("size") or v.get("label") or "")
                r = match_top_size(sz); sizes.add(r) if r else None
                r, l = match_bottom_alpha_size(sz)
                if r: sizes.add(r); has_long |= l
        if not discounts:
            return _no_sale(self.brand_name, url)
        max_d = max(discounts)
        if max_d < SALE_THRESHOLD_PCT:
            return _no_sale(self.brand_name, url)
        return SaleInfo(
            brand=self.brand_name, is_on_sale=True,
            sale_type="percent-off", discount_pct=round(max_d), sale_url=url,
            sizes_available=sorted(sizes), has_long_option=has_long,
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
