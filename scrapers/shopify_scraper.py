"""
Generic Shopify scraper used by all Shopify-based brands.

Uses the public Shopify JSON API (/collections/<slug>/products.json) —
no authentication required.

Strategy:
  1. Try /collections/<sale_collection>/products.json
  2. If 404, fall back to /collections/all/products.json filtered by compare_at_price
"""

from __future__ import annotations

import time
import requests

from .base import BaseScraper, SaleInfo
from size_checker import check_products_for_sizes
from config import SALE_THRESHOLD_PCT, REQUEST_TIMEOUT, REQUEST_DELAY


class ShopifyScraper(BaseScraper):

    def __init__(
        self,
        brand_name: str,
        domain: str,
        sale_collection: str = "sale",
        low_frequency: bool = False,
    ):
        self.brand_name      = brand_name
        self.domain          = domain.rstrip('/')
        self.sale_collection = sale_collection
        self.sale_url        = f"https://{self.domain}/collections/{sale_collection}"
        self.low_frequency   = low_frequency

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def check_sale(self) -> SaleInfo:
        try:
            products = self._fetch_collection(self.sale_collection)
        except Exception as exc:
            return self.make_error_result(f"Fetch error: {exc}")

        if products is None:
            # No dedicated sale collection — check all products
            try:
                return self._check_via_all_products()
            except Exception as exc:
                return self.make_error_result(f"Fallback fetch error: {exc}")

        return self._build_result(products, source="sale-collection")

    # ------------------------------------------------------------------
    # Fetch helpers
    # ------------------------------------------------------------------

    def _fetch_collection(self, collection: str) -> list | None:
        """
        Page through /collections/<slug>/products.json.
        Returns None on 404 (collection missing), raises on other errors.
        """
        products: list[dict] = []
        page = 1

        while True:
            url = (
                f"https://{self.domain}/collections/{collection}"
                f"/products.json?limit=250&page={page}"
            )
            resp = requests.get(url, headers=self.HEADERS, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 404:
                return None
            resp.raise_for_status()

            batch = resp.json().get("products", [])
            products.extend(batch)

            if len(batch) < 250:
                break
            page += 1
            time.sleep(REQUEST_DELAY)

        return products

    def _check_via_all_products(self) -> SaleInfo:
        all_products = self._fetch_collection("all") or []
        discounted = [p for p in all_products if _has_discount(p)]
        return self._build_result(
            discounted,
            source="all-filtered",
            sale_url_override=f"https://{self.domain}",
        )

    # ------------------------------------------------------------------
    # Result builder
    # ------------------------------------------------------------------

    def _build_result(
        self,
        products: list,
        source: str,
        sale_url_override: str | None = None,
    ) -> SaleInfo:
        url = sale_url_override or self.sale_url

        if not products:
            return SaleInfo(
                brand=self.brand_name,
                is_on_sale=False,
                sale_type="none",
                discount_pct=None,
                sale_url=url,
                low_frequency=self.low_frequency,
            )

        max_disc, _ = _compute_discounts(products)

        # A dedicated sale collection qualifies unconditionally;
        # products surfaced via all-products filter need >= threshold
        qualifies = (source == "sale-collection") or (max_disc >= SALE_THRESHOLD_PCT)

        if not qualifies:
            return SaleInfo(
                brand=self.brand_name,
                is_on_sale=False,
                sale_type="below-threshold",
                discount_pct=round(max_disc, 1) if max_disc else None,
                sale_url=url,
                low_frequency=self.low_frequency,
            )

        sizes, has_long = check_products_for_sizes(products)

        if max_disc >= 50:
            sale_type = "clearance"
        elif max_disc >= SALE_THRESHOLD_PCT:
            sale_type = "percent-off"
        else:
            sale_type = "sale"

        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=True,
            sale_type=sale_type,
            discount_pct=round(max_disc) if max_disc else None,
            sale_url=url,
            sizes_available=sizes,
            has_long_option=has_long,
            low_frequency=self.low_frequency,
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _has_discount(product: dict, min_pct: float = 5.0) -> bool:
    for v in product.get("variants", []):
        cap, price = v.get("compare_at_price"), v.get("price")
        if cap and price:
            try:
                c, p = float(cap), float(price)
                if c > 0 and (c - p) / c * 100 >= min_pct:
                    return True
            except (ValueError, TypeError):
                pass
    return False


def _compute_discounts(products: list) -> tuple[float, float]:
    """Return (max_pct, avg_pct) across all discounted variants."""
    discounts: list[float] = []
    for product in products:
        for v in product.get("variants", []):
            cap, price = v.get("compare_at_price"), v.get("price")
            if cap and price:
                try:
                    c, p = float(cap), float(price)
                    if c > p > 0:
                        discounts.append((c - p) / c * 100)
                except (ValueError, TypeError):
                    pass
    if not discounts:
        return 0.0, 0.0
    return max(discounts), sum(discounts) / len(discounts)
