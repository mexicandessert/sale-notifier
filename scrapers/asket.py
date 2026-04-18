"""
Asket scraper.

Asket is a Swedish DTC brand that rarely runs traditional sales.
They have a permanent "Outlet" section at /en-us/products/outlet.
We report when that section is non-empty (they always carry some outlet stock)
ONLY when the discount is >= SALE_THRESHOLD_PCT or it's flagged as a special event.

Strategy:
  1. Check the outlet page for products with compare_at_price data
     (Asket uses a custom platform with JSON embedded in page scripts)
  2. Also look for any sitewide sale banners / promo pages
"""

from __future__ import annotations

import json
import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from size_checker import match_top_size, match_bottom_inch_size, match_bottom_alpha_size
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

OUTLET_URL = "https://www.asket.com/en-us/products/outlet"
HOME_URL   = "https://www.asket.com/en-us"


class AsketScraper(BaseScraper):
    brand_name    = "Asket"
    sale_url      = OUTLET_URL
    low_frequency = False

    def check_sale(self) -> SaleInfo:
        try:
            return self._scrape()
        except Exception as exc:
            return self.make_error_result(str(exc))

    def _scrape(self) -> SaleInfo:
        # First check homepage for site-wide sale banner
        site_wide = self._check_sitewide_banner()

        # Then check outlet page
        resp = requests.get(
            OUTLET_URL,
            headers={**self.HEADERS, "Accept": "text/html"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        if site_wide:
            return SaleInfo(
                brand=self.brand_name,
                is_on_sale=True,
                sale_type="site-wide",
                discount_pct=None,
                sale_url=OUTLET_URL,
            )

        # Look for embedded JSON product data
        result = self._parse_page_json(soup, resp.text)
        if result is not None:
            return result

        # Fallback: does the outlet page have actual products listed?
        return self._html_fallback(soup, resp.text)

    # ------------------------------------------------------------------

    def _check_sitewide_banner(self) -> bool:
        try:
            resp = requests.get(
                HOME_URL,
                headers={**self.HEADERS, "Accept": "text/html"},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.ok:
                return bool(re.search(
                    r'site.?wide|extra\s+\d+%\s+off|sale\s+on\s+now',
                    resp.text, re.IGNORECASE
                ))
        except Exception:
            pass
        return False

    def _parse_page_json(self, soup: BeautifulSoup, raw_html: str) -> SaleInfo | None:
        """
        Asket bakes product data into inline <script> tags as JSON.
        Try to find and parse it.
        """
        discounts: list[float] = []
        sizes_found: set[str] = set()
        has_long = False

        for tag in soup.find_all("script"):
            content = tag.string or ""
            # Look for JSON-shaped product arrays
            json_matches = re.findall(r'\{[^<]{50,}\}', content)
            for raw in json_matches:
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                orig = _coerce_float(obj.get("compareAtPrice") or obj.get("originalPrice"))
                curr = _coerce_float(obj.get("price") or obj.get("currentPrice"))
                if orig and curr and orig > curr > 0:
                    discounts.append((orig - curr) / orig * 100)

                for sz in _extract_size_strings(obj):
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
            return None

        max_disc = max(discounts)
        if max_disc < SALE_THRESHOLD_PCT:
            return None

        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=True,
            sale_type="clearance" if max_disc >= 50 else "percent-off",
            discount_pct=round(max_disc),
            sale_url=OUTLET_URL,
            sizes_available=sorted(sizes_found),
            has_long_option=has_long,
        )

    def _html_fallback(self, soup: BeautifulSoup, raw_html: str) -> SaleInfo:
        # Check for discount patterns
        pct_matches = re.findall(r'(\d{2,3})\s*%\s*off', raw_html, re.IGNORECASE)
        if pct_matches:
            max_disc = max(int(p) for p in pct_matches)
            if max_disc >= SALE_THRESHOLD_PCT:
                return SaleInfo(
                    brand=self.brand_name,
                    is_on_sale=True,
                    sale_type="clearance" if max_disc >= 50 else "percent-off",
                    discount_pct=max_disc,
                    sale_url=OUTLET_URL,
                )

        # Check if the outlet page has any product cards at all
        product_cards = soup.find_all(class_=re.compile(r'product|item|card', re.I))
        if len(product_cards) > 3:
            # Outlet exists but no discount % found; report as "outlet" only if
            # we can find struck-through/original prices
            has_strikethrough = bool(
                soup.find_all(["s", "del", "strike"])
                or soup.find_all(class_=re.compile(r'original|was|compare|strike', re.I))
            )
            if has_strikethrough:
                return SaleInfo(
                    brand=self.brand_name,
                    is_on_sale=True,
                    sale_type="percent-off",
                    discount_pct=None,
                    sale_url=OUTLET_URL,
                )

        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=False,
            sale_type="none",
            discount_pct=None,
            sale_url=OUTLET_URL,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _extract_size_strings(obj: dict) -> list[str]:
    out = []
    for key in ("size", "sizeLabel", "value", "label", "name"):
        v = obj.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    return out
