"""
Telegram notification sender.

Formats and sends a single consolidated daily message summarising all new
qualifying sales.

Telegram message limits:
  - Max 4096 chars per message (MarkdownV2 mode)
  - We split into multiple messages if needed
"""

from __future__ import annotations

import os
import re
import textwrap
from datetime import datetime, timezone

import requests

from scrapers.base import SaleInfo

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Characters that must be escaped in Telegram MarkdownV2
_MD_SPECIAL = re.compile(r'([_\*\[\]\(\)~`>#+\-=|{}.!\\])')


def _esc(text: str) -> str:
    """Escape special MarkdownV2 characters."""
    return _MD_SPECIAL.sub(r'\\\1', str(text))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_new_sales_notification(
    new_sales: list[SaleInfo],
    all_results: list[SaleInfo],
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> bool:
    """
    Build and send the daily Telegram digest.
    Returns True on success, False if nothing was sent or an error occurred.
    """
    token   = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat    = chat_id   or os.environ.get("TELEGRAM_CHAT_ID",   "")

    if not token or not chat:
        print("[notifier] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping send.")
        return False

    if not new_sales:
        print("[notifier] No new sales — nothing to send.")
        return False

    messages = _build_messages(new_sales, all_results)

    success = True
    for msg in messages:
        ok = _send(token, chat, msg)
        if not ok:
            success = False
    return success


def send_error_summary(errors: list[tuple[str, str]], bot_token: str | None = None, chat_id: str | None = None) -> None:
    """Optionally send a short error digest when scrapers fail (non-blocking)."""
    if not errors:
        return
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat  = chat_id   or os.environ.get("TELEGRAM_CHAT_ID",   "")
    if not token or not chat:
        return

    lines = [f"⚠️ *Sale Monitor — Scraper Errors*\n"]
    for brand, err in errors[:10]:  # cap at 10
        lines.append(f"• {_esc(brand)}: {_esc(err[:120])}")
    _send(token, chat, "\n".join(lines))


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def _build_messages(new_sales: list[SaleInfo], all_results: list[SaleInfo]) -> list[str]:
    date_str = datetime.now(timezone.utc).strftime("%B %-d, %Y")
    header   = f"🛍 *Sale Monitor — {_esc(date_str)}*\n\n"
    header  += f"*{len(new_sales)} new sale{'s' if len(new_sales) != 1 else ''} detected\\!*\n"
    header  += "━" * 28 + "\n"

    blocks: list[str] = []
    for info in new_sales:
        blocks.append(_format_brand_block(info))

    # Footer: brands still on sale (carry-overs not re-notified)
    ongoing = [r for r in all_results if r.is_on_sale and r.brand not in {s.brand for s in new_sales}]
    if ongoing:
        footer = "\n\n📌 *Also ongoing:* " + _esc(", ".join(s.brand for s in ongoing))
    else:
        footer = ""

    # Split into ≤4096-char messages
    return _paginate(header, blocks, footer)


def _format_brand_block(info: SaleInfo) -> str:
    lines: list[str] = []

    # Brand name + low-frequency flag
    brand_line = f"*{_esc(info.brand)}*"
    if info.low_frequency:
        brand_line += " 🔔 _\\(rare sale\\)_"
    lines.append(brand_line)

    # Sale type
    sale_label = {
        "site-wide":    "Site\\-wide sale",
        "clearance":    "Clearance",
        "percent-off":  "Discount sale",
        "sale":         "Sale",
    }.get(info.sale_type, _esc(info.sale_type.replace("-", "\\-")))
    lines.append(f"  Type: {sale_label}")

    # Discount %
    if info.discount_pct:
        lines.append(f"  Discount: up to *{_esc(str(int(info.discount_pct)))}%* off")

    # Link
    lines.append(f"  [View sale]({info.sale_url})")

    # Sizes
    if info.sizes_available:
        # Separate MTO note from regular sizes
        mto = [s for s in info.sizes_available if "MTO" in s or "measurements" in s.lower()]
        regular = [s for s in info.sizes_available if s not in mto]

        if regular:
            sizes_str = _esc(", ".join(regular))
            lines.append(f"  Sizes in stock: {sizes_str}")
        if mto:
            lines.append(f"  _{_esc(mto[0])}_")
        if info.has_long_option:
            lines.append("  ✅ Long inseam / tall cut available")
    else:
        lines.append("  _Sizes: verify on site_")

    return "\n".join(lines)


def _paginate(header: str, blocks: list[str], footer: str, limit: int = 4000) -> list[str]:
    """
    Distribute brand blocks across messages so each is under `limit` chars.
    """
    messages: list[str] = []
    current = header

    for i, block in enumerate(blocks):
        sep = "\n\n" if i > 0 else ""
        chunk = sep + block
        candidate = current + chunk

        if len(candidate) > limit and current != header:
            messages.append(current.rstrip())
            current = header + block
        else:
            current = candidate

    current += footer
    messages.append(current.rstrip())
    return messages


# ---------------------------------------------------------------------------
# HTTP send
# ---------------------------------------------------------------------------

def _send(token: str, chat_id: str, text: str) -> bool:
    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if not resp.ok:
            print(f"[notifier] Telegram API error {resp.status_code}: {resp.text[:200]}")
            # Retry once without markdown in case of parse error
            payload["parse_mode"] = None
            payload["text"] = _strip_markdown(text)
            resp2 = requests.post(url, json=payload, timeout=15)
            return resp2.ok
        return True
    except requests.RequestException as exc:
        print(f"[notifier] Failed to send Telegram message: {exc}")
        return False


def _strip_markdown(text: str) -> str:
    """Minimal plain-text fallback — remove common MarkdownV2 syntax."""
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\\([_*\[\]()~`>#+\-=|{}.!\\])', r'\1', text)
    return text
