"""
State persistence for the sale monitor.

The state file (state.json) tracks what we've seen on each previous run
so we can distinguish NEW sales from ongoing ones.

State schema:
{
  "last_run": "2024-01-15T09:00:00Z",
  "brands": {
    "Todd Snyder": {
      "is_on_sale":       true,
      "sale_type":        "clearance",
      "discount_pct":     40.0,
      "sale_url":         "https://toddsnyder.com/collections/sale",
      "sizes_available":  ["L", "XL"],
      "has_long_option":  false,
      "first_detected":   "2024-01-14T09:00:00Z",
      "last_seen":        "2024-01-15T09:00:00Z",
      "notified":         true        // true once we've sent a Telegram message
    },
    ...
  }
}

A sale is "new" (trigger notification) when:
  - is_on_sale is True AND
  - previous state had is_on_sale False (or brand was absent)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from scrapers.base import SaleInfo

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """Load previous run state from disk. Returns empty structure on first run."""
    if not os.path.exists(STATE_FILE):
        return {"last_run": None, "brands": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {"last_run": None, "brands": {}}


def save_state(state: dict) -> None:
    """Write updated state back to disk (atomic via temp-file swap)."""
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


# ---------------------------------------------------------------------------
# Diffing logic
# ---------------------------------------------------------------------------

def compute_new_sales(
    results: list[SaleInfo],
    prev_state: dict,
) -> list[SaleInfo]:
    """
    Return the subset of results that represent NEW sales —
    i.e. brands that were not on sale in the previous run.
    """
    prev_brands: dict[str, dict] = prev_state.get("brands", {})
    new: list[SaleInfo] = []

    for info in results:
        if not info.is_on_sale:
            continue
        prev = prev_brands.get(info.brand, {})
        was_on_sale = prev.get("is_on_sale", False)
        # Treat a scraping error on the previous run as "unknown", not "no sale"
        prev_had_error = prev.get("sale_type") == "error"

        if not was_on_sale and not prev_had_error:
            new.append(info)

    return new


# ---------------------------------------------------------------------------
# State update
# ---------------------------------------------------------------------------

def update_state(
    state: dict,
    results: list[SaleInfo],
    new_sales: list[SaleInfo],
) -> dict:
    """
    Merge the latest scrape results into the state dict.
    Marks brands as notified if they appear in new_sales.
    Returns the updated state (also mutates in place).
    """
    now = _now_iso()
    state["last_run"] = now

    brands_state: dict[str, Any] = state.setdefault("brands", {})
    notified_names = {s.brand for s in new_sales}

    for info in results:
        prev = brands_state.get(info.brand, {})

        if info.is_on_sale:
            brands_state[info.brand] = {
                "is_on_sale":      True,
                "sale_type":       info.sale_type,
                "discount_pct":    info.discount_pct,
                "sale_url":        info.sale_url,
                "sizes_available": info.sizes_available,
                "has_long_option": info.has_long_option,
                "low_frequency":   info.low_frequency,
                "first_detected":  prev.get("first_detected") or now,
                "last_seen":       now,
                # Keep notified=True once set; set on new detection
                "notified":        prev.get("notified", False) or (info.brand in notified_names),
                "error":           info.error,
            }
        else:
            # Sale ended (or errored) — reset notified so we alert again next time it starts
            brands_state[info.brand] = {
                "is_on_sale":     False,
                "sale_type":      info.sale_type,
                "discount_pct":   info.discount_pct,
                "sale_url":       info.sale_url,
                "low_frequency":  info.low_frequency,
                "last_seen":      prev.get("last_seen"),
                "notified":       False,
                "error":          info.error,
            }

    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
