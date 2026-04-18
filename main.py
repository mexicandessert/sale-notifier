"""
Sale Monitor — main entry point.

Run order:
  1. Load previous state from state.json
  2. Run all brand scrapers (Shopify + custom)
  3. Diff results against previous state to find NEW sales
  4. If new sales exist (or FORCE_NOTIFY=true), send Telegram message
  5. Save updated state back to state.json

GitHub Actions commits state.json after this script exits.
"""

from __future__ import annotations

import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from scrapers.base import BaseScraper, SaleInfo

# ── Custom scrapers ──────────────────────────────────────────────────────────
from scrapers.banana_republic import BananaRepublicScraper
from scrapers.madewell        import MadewellScraper
from scrapers.jcrew           import JCrewScraper
from scrapers.abercrombie     import AbercrombieScraper
from scrapers.ralph_lauren    import RalphLaurenScraper
from scrapers.asics           import AsicsScraper
from scrapers.lululemon       import LululemonScraper
from scrapers.massimo_dutti   import MassimoDuttiScraper
from scrapers.reiss           import ReissScraper
from scrapers.levis           import LevisScraper
from scrapers.asket           import AsketScraper
from scrapers.proper_cloth    import ProperClothScraper
from scrapers.huckberry       import HuckberryScraper

# ── Shopify scrapers (config-driven) ─────────────────────────────────────────
from brands_config import build_shopify_scrapers

# ── Infrastructure ────────────────────────────────────────────────────────────
from state_manager import load_state, save_state, compute_new_sales, update_state
from notifier      import send_new_sales_notification, send_error_summary

# ---------------------------------------------------------------------------
# Scraper registry
# ---------------------------------------------------------------------------

CUSTOM_SCRAPERS: list[BaseScraper] = [
    BananaRepublicScraper(),
    MadewellScraper(),
    JCrewScraper(),
    AbercrombieScraper(),
    RalphLaurenScraper(),
    AsicsScraper(),
    LululemonScraper(),
    MassimoDuttiScraper(),
    ReissScraper(),
    LevisScraper(),
    AsketScraper(),
    ProperClothScraper(),
    HuckberryScraper(),
]

MAX_WORKERS = 8   # concurrent HTTP workers


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    force_notify = os.environ.get("FORCE_NOTIFY", "false").lower() == "true"

    print("=" * 60)
    print("Sale Monitor starting")
    print(f"Force notify: {force_notify}")
    print("=" * 60)

    # ── Build full scraper list ───────────────────────────────────────
    all_scrapers: list[BaseScraper] = build_shopify_scrapers() + CUSTOM_SCRAPERS
    print(f"Loaded {len(all_scrapers)} brand scrapers")

    # ── Load previous state ───────────────────────────────────────────
    prev_state = load_state()
    print(f"Previous run: {prev_state.get('last_run', 'never')}\n")

    # ── Run scrapers concurrently ─────────────────────────────────────
    results: list[SaleInfo] = []
    errors:  list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_brand = {
            pool.submit(_run_scraper, scraper): scraper.brand_name
            for scraper in all_scrapers
        }

        for future in as_completed(future_to_brand):
            brand = future_to_brand[future]
            try:
                info = future.result()
                results.append(info)
                _log_result(info)
                if info.error and info.sale_type == "error":
                    errors.append((brand, info.error))
            except Exception as exc:
                tb = traceback.format_exc()
                print(f"[{brand}] UNEXPECTED EXCEPTION:\n{tb}")
                errors.append((brand, str(exc)))

    # Sort results alphabetically for consistent output
    results.sort(key=lambda r: r.brand.lower())

    # ── Compute new sales ─────────────────────────────────────────────
    new_sales = compute_new_sales(results, prev_state)
    print(f"\n{'─'*40}")
    print(f"Total brands checked : {len(results)}")
    print(f"Currently on sale    : {sum(1 for r in results if r.is_on_sale)}")
    print(f"NEW sales this run   : {len(new_sales)}")
    print(f"Scraper errors       : {len(errors)}")
    print(f"{'─'*40}\n")

    if new_sales:
        print("NEW SALES:")
        for s in new_sales:
            print(f"  • {s.brand}  ({s.sale_type}, {s.discount_pct or '?'}% off)")
    else:
        print("No new sales detected.")

    # ── Send notification ─────────────────────────────────────────────
    if new_sales or force_notify:
        target = new_sales if new_sales else [r for r in results if r.is_on_sale]
        ok = send_new_sales_notification(target, results)
        if ok:
            print("\nTelegram notification sent.")
        else:
            print("\nFailed to send Telegram notification (check token/chat ID).")
    else:
        print("No notification sent.")

    # Send error digest (non-blocking, best-effort)
    if errors:
        send_error_summary(errors)

    # ── Save updated state ────────────────────────────────────────────
    new_state = update_state(prev_state, results, new_sales)
    save_state(new_state)
    print("State saved to state.json")

    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_scraper(scraper: BaseScraper) -> SaleInfo:
    """Call check_sale() and wrap any uncaught exception into an error SaleInfo."""
    try:
        return scraper.check_sale()
    except Exception as exc:
        return scraper.make_error_result(f"Uncaught: {exc}")


def _log_result(info: SaleInfo) -> None:
    status = "ON SALE" if info.is_on_sale else "no sale"
    disc   = f"  ({info.discount_pct:.0f}% off)" if info.discount_pct else ""
    err    = f"  ERROR: {info.error}" if info.error else ""
    lf     = " [rare brand]" if info.low_frequency else ""
    print(f"  [{status:^8}] {info.brand}{lf}{disc}{err}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())
