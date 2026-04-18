"""
Polo Ralph Lauren + RRL scraper.

Monitors both the main PRL sale section and the RRL sub-brand.

Strategy:
  - Fetch sale page HTML and look for __NEXT_DATA__ or window.__PRELOADED_STATE__ JSON.
  - Use Selenium as a fallback when JS rendering is required.
  - PRL sale: https://www.ralphlauren.com/en-us/category/sale
  - RRL sale:  https://www.ralphlauren.com/en-us/category/rrl-sale
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import match_top_size, match_bottom_inch_size, match_bottom_alpha_size, match_shoe_size
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

PRL_SALE_URL = "https://www.ralphlauren.com/en-us/category/sale"
RRL_SALE_URL = "https://www.ralphlauren.com/en-us/category/rrl-sale"


class RalphLaurenScraper(BaseScraper):
    brand_name    = "Polo Ralph Lauren"
    sale_url      = PRL_SALE_URL
    low_frequency = False

    def check_sale(self) -> SaleInfo:
        try:
            return self._scrape()
        except Exception as exc:
            return self.make_error_result(str(exc))

    def _scrape(self) -> SaleInfo:
        headers = {
            **self.HEADERS,
            "Referer": "https://www.ralphlauren.com/",
            "sec-fetch-site": "same-origin",
        }

        results = []
        for url, label in [(PRL_SALE_URL, "PRL"), (RRL_SALE_URL, "RRL")]:
            try:
                resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                r = self._parse_page(resp.text, url)
                results.append(r)
            except Exception:
                pass

        # Return most relevant result (on-sale preferred)
        for r in results:
            if r.is_on_sale:
                # Combine RRL note into brand name if it's the RRL sale
                return r
        return results[0] if results else self.make_error_result("No pages fetched")

    def _parse_page(self, raw: str, url: str) -> SaleInfo:
        soup = BeautifulSoup(raw, "lxml")

        # Try window.__PRELOADED_STATE__ (common on Ralph Lauren)
        for script in soup.find_all("script"):
            text = script.string or ""
            m = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.+?\});', text, re.DOTALL)
            if m:
                try:
                    state = json.loads(m.group(1))
                    result = self._parse_state(state, url)
                    if result.is_on_sale:
                        return result
                except Exception:
                    pass

        # Try __NEXT_DATA__
        next_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_tag and next_tag.string:
            try:
                data = json.loads(next_tag.string)
                result = self._parse_state(data, url)
                if result.is_on_sale:
                    return result
            except Exception:
                pass

        # HTML fallback
        return self._html_fallback(raw, url)

    def _parse_state(self, data: dict, url: str) -> SaleInfo:
        products = _deep_find_list(data, "products") or _deep_find_list(data, "items") or []
        discounts: list[float] = []
        sizes: set[str] = set()
        has_long = False

        for p in products:
            orig = _to_float(p.get("listPrice") or p.get("originalPrice"))
            curr = _to_float(p.get("salePrice") or p.get("price"))
            if orig and curr and orig > curr > 0:
                discounts.append((orig - curr) / orig * 100)

            for v in p.get("variants", []) or p.get("sizes", []) or []:
                sz = str(v.get("size") or v.get("label") or v.get("value") or "")
                if not sz: continue
                r = match_top_size(sz); sizes.add(r) if r else None
                r = match_shoe_size(sz); sizes.add(r) if r else None
                r, l = match_bottom_inch_size(sz)
                if r: sizes.add(r); has_long |= l
                r, l = match_bottom_alpha_size(sz)
                if r: sizes.add(r); has_long |= l

        if not discounts:
            return _no_sale(self.brand_name, url)

        max_d = max(discounts)
        if max_d < SALE_THRESHOLD_PCT:
            return _no_sale(self.brand_name, url)

        is_rrl = "rrl" in url
        brand_label = "RRL (Ralph Lauren)" if is_rrl else self.brand_name

        return SaleInfo(
            brand=brand_label, is_on_sale=True,
            sale_type="clearance" if max_d >= 50 else "percent-off",
            discount_pct=round(max_d), sale_url=url,
            sizes_available=sorted(sizes), has_long_option=has_long,
        )

    def _html_fallback(self, raw: str, url: str) -> SaleInfo:
        pcts = re.findall(r'(\d{2,3})\s*%\s*off', raw, re.I)
        if not pcts:
            # Check for "SALE" heading with no percent info — still report
            has_sale_section = bool(re.search(r'<h[123][^>]*>\s*sale\s*</h', raw, re.I))
            if has_sale_section:
                return SaleInfo(
                    brand=self.brand_name, is_on_sale=True,
                    sale_type="sale", discount_pct=None, sale_url=url,
                    sizes_available=[],
                    error="Discount % could not be parsed — verify on site",
                )
            return _no_sale(self.brand_name, url)

        max_d = max(int(p) for p in pcts)
        if max_d < SALE_THRESHOLD_PCT:
            return _no_sale(self.brand_name, url)

        return SaleInfo(
            brand=self.brand_name, is_on_sale=True,
            sale_type="percent-off", discount_pct=max_d, sale_url=url,
            sizes_available=[],
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
