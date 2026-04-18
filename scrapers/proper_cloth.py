"""
Proper Cloth scraper.

Proper Cloth is a made-to-measure (MTO) shirtmaker.
They do NOT have traditional inventory sizes — every shirt is cut to
the customer's specific measurements.

What we DO monitor:
  - Fabric / shirt discounts on their sale page
  - Promotional discount codes announced on the site
  - End-of-season fabric clearances

Size filtering note:
  Standard size filtering does NOT apply here. Instead, we just detect
  whether there's any discount ≥ SALE_THRESHOLD_PCT on fabrics/styles,
  and flag that the user should visit and enter their saved measurements.
"""

from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, SaleInfo
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT

SALE_URL = "https://propercloth.com/reference/sale-fabrics/"
PROMO_URL = "https://propercloth.com"


class ProperClothScraper(BaseScraper):
    brand_name    = "Proper Cloth"
    sale_url      = SALE_URL
    low_frequency = False

    def check_sale(self) -> SaleInfo:
        try:
            return self._scrape()
        except Exception as exc:
            return self.make_error_result(str(exc))

    def _scrape(self) -> SaleInfo:
        # Check the main site for a promo banner first
        site_promo = self._check_sitewide_promo()
        if site_promo:
            return site_promo

        # Check the sale fabrics page
        resp = requests.get(
            SALE_URL,
            headers={**self.HEADERS, "Accept": "text/html"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse_sale_page(soup, resp.text)

    # ------------------------------------------------------------------

    def _check_sitewide_promo(self) -> SaleInfo | None:
        """Look for a sitewide promo code or banner on the homepage."""
        try:
            resp = requests.get(
                PROMO_URL,
                headers={**self.HEADERS, "Accept": "text/html"},
                timeout=REQUEST_TIMEOUT,
            )
            if not resp.ok:
                return None
            raw = resp.text

            # Look for a percentage discount announcement
            pct_matches = re.findall(r'(\d{2,3})\s*%\s*off', raw, re.IGNORECASE)
            if pct_matches:
                max_disc = max(int(p) for p in pct_matches)
                if max_disc >= SALE_THRESHOLD_PCT:
                    site_wide = bool(re.search(
                        r'site.?wide|all\s+(shirts?|orders?|fabric)|everything',
                        raw, re.IGNORECASE
                    ))
                    return SaleInfo(
                        brand=self.brand_name,
                        is_on_sale=True,
                        sale_type="site-wide" if site_wide else "percent-off",
                        discount_pct=max_disc,
                        sale_url=PROMO_URL,
                        sizes_available=["MTO — enter your measurements on site"],
                        has_long_option=False,
                    )
        except Exception:
            pass
        return None

    def _parse_sale_page(self, soup: BeautifulSoup, raw_html: str) -> SaleInfo:
        page_text = soup.get_text(" ", strip=True)

        # Count fabric/product tiles on the sale page
        fabric_tiles = (
            soup.find_all(class_=re.compile(r'fabric|product|swatch|item', re.I))
        )
        has_sale_items = len(fabric_tiles) > 2

        # Look for discount indicators
        pct_matches = re.findall(r'(\d{2,3})\s*%\s*off', raw_html, re.IGNORECASE)
        strikethrough = bool(
            soup.find_all(["s", "del", "strike"])
            or soup.find_all(class_=re.compile(r'original|was|compare|strike|discount', re.I))
        )

        if not has_sale_items and not pct_matches and not strikethrough:
            return SaleInfo(
                brand=self.brand_name,
                is_on_sale=False,
                sale_type="none",
                discount_pct=None,
                sale_url=SALE_URL,
            )

        if pct_matches:
            max_disc = max(int(p) for p in pct_matches)
            if max_disc < SALE_THRESHOLD_PCT and not has_sale_items:
                return SaleInfo(
                    brand=self.brand_name,
                    is_on_sale=False,
                    sale_type="below-threshold",
                    discount_pct=max_disc,
                    sale_url=SALE_URL,
                )
            disc = max_disc if max_disc >= SALE_THRESHOLD_PCT else None
        else:
            disc = None

        if has_sale_items or disc:
            return SaleInfo(
                brand=self.brand_name,
                is_on_sale=True,
                sale_type="clearance" if (disc and disc >= 50) else "percent-off",
                discount_pct=disc,
                sale_url=SALE_URL,
                # MTO: size filtering doesn't apply — user enters own measurements
                sizes_available=["MTO — enter your measurements on site"],
                has_long_option=False,
            )

        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=False,
            sale_type="none",
            discount_pct=None,
            sale_url=SALE_URL,
        )
