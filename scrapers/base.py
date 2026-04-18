"""
Base classes and shared data model for all brand scrapers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SaleInfo:
    """Current sale status for one brand."""

    brand: str
    is_on_sale: bool
    sale_type: str                   # "site-wide" | "clearance" | "percent-off" | "sale" | "none"
    discount_pct: Optional[float]    # Max discount found; None if unknown
    sale_url: str                    # Direct link to the sale section
    sizes_available: list[str] = field(default_factory=list)
    has_long_option: bool = False    # Long inseam / tall cut available
    error: Optional[str] = None     # Non-None when scraping failed
    low_frequency: bool = False      # Brand rarely runs sales


class BaseScraper(ABC):
    """Abstract base that every brand scraper must implement."""

    brand_name: str
    sale_url: str
    low_frequency: bool = False

    # Realistic browser headers used by all scrapers
    HEADERS: dict = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }

    JSON_HEADERS: dict = {
        **HEADERS,
        "Accept": "application/json, text/plain, */*",
    }

    @abstractmethod
    def check_sale(self) -> SaleInfo:
        """
        Scrape the brand's website and return a SaleInfo.
        Must never raise — catch all exceptions and return make_error_result().
        """
        ...

    def make_error_result(self, error: str) -> SaleInfo:
        return SaleInfo(
            brand=self.brand_name,
            is_on_sale=False,
            sale_type="error",
            discount_pct=None,
            sale_url=self.sale_url,
            error=error,
            low_frequency=self.low_frequency,
        )
