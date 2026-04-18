"""
Size parsing and matching utilities.

Parses Shopify product variant options (and plain size strings) against the
user's size preferences defined in config.py.
"""

from __future__ import annotations

import re
from config import USER_SIZES

# ---------------------------------------------------------------------------
# Derived constants
# ---------------------------------------------------------------------------

TOP_SIZES_UPPER = {s.upper() for s in USER_SIZES["tops"]}

BOTTOM_WAISTS     = set(USER_SIZES["bottoms_inch"]["waist"])
BOTTOM_INSEAM_MIN = USER_SIZES["bottoms_inch"]["inseam_min"]
BOTTOM_LONG_FROM  = USER_SIZES["bottoms_inch"]["inseam_ideal_min"]

BOTTOM_ALPHA_UPPER = {s.upper() for s in USER_SIZES["bottoms_alpha"]}

SHOE_US = {str(s) for s in USER_SIZES["shoes_us"]}
SHOE_EU = {str(s) for s in USER_SIZES["shoes_eu"]}

_LONG_RE = re.compile(r'\b(long|tall|lng)\b', re.IGNORECASE)

# ---------------------------------------------------------------------------
# Individual size matchers
# ---------------------------------------------------------------------------

def match_top_size(option: str) -> str | None:
    """Return 'L' or 'XL' if the option matches a user top size, else None."""
    n = option.strip().lower()
    parts = re.split(r'[\s/\-_|,]+', n)
    for part in parts:
        if part in ('xl', 'x-large', 'xlarge', 'extra-large', 'extra large') and 'XL' in TOP_SIZES_UPPER:
            return 'XL'
        if part in ('l', 'large') and 'L' in TOP_SIZES_UPPER:
            return 'L'
    return None


def match_bottom_inch_size(option: str) -> tuple[str | None, bool]:
    """
    Parse an inch-based bottom size (e.g. '34x32', 'W34 L34', '34/34').
    Returns (label, is_long) or (None, False).
    """
    n = option.strip().lower().replace('"', '').replace("'", '').replace('\u2032', '')

    patterns = [
        r'w?\s*(\d{2})\s*[x×/\-]\s*(\d{2})',   # 34x32, 34/32, W34-32
        r'w(\d{2})\s+l(\d{2})',                  # W34 L32
        r'\b(\d{2})\s+(\d{2})\b',               # "34 32"
    ]
    for pat in patterns:
        m = re.search(pat, n)
        if m:
            try:
                waist  = int(m.group(1))
                inseam = float(m.group(2))
            except ValueError:
                continue
            if waist in BOTTOM_WAISTS and inseam >= BOTTOM_INSEAM_MIN:
                is_long = inseam >= BOTTOM_LONG_FROM
                return f"{waist}x{int(inseam)}", is_long
    return None, False


def match_bottom_alpha_size(option: str) -> tuple[str | None, bool]:
    """
    Check for letter-based bottom size (L) and detect long/tall cut.
    Returns (label, is_long) or (None, False).
    """
    n = option.strip().lower()
    is_long = bool(_LONG_RE.search(n))
    parts = re.split(r'[\s/\-_|,]+', n)
    for part in parts:
        if part in ('l', 'large') and 'L' in BOTTOM_ALPHA_UPPER:
            return 'L', is_long
    return None, False


def match_shoe_size(option: str) -> str | None:
    """Return a matched shoe size label ('US 12', 'EU 45', etc.) or None."""
    n = option.strip().lower()
    is_eu = bool(re.search(r'\b(eu|eur|european)\b', n))

    numbers = re.findall(r'\d+(?:\.\d+)?', n)
    for num_str in numbers:
        try:
            f = float(num_str)
            normalized = str(int(f)) if f == int(f) else num_str
        except ValueError:
            normalized = num_str

        if is_eu:
            if normalized in SHOE_EU:
                return f"EU {normalized}"
        else:
            if normalized in SHOE_US:
                return f"US {normalized}"
            # Unambiguously large numbers → EU range
            try:
                if float(normalized) >= 40 and normalized in SHOE_EU:
                    return f"EU {normalized}"
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------------------
# Product categorisation (used with Shopify product dicts)
# ---------------------------------------------------------------------------

_SHOE_KW   = re.compile(r'\b(shoe|sneaker|boot|loafer|oxford|footwear|sandal|slipper|trainer|runner|mule)\b', re.I)
_BOTTOM_KW = re.compile(r'\b(pant|trouser|jean|chino|short|denim|bottom|slack|cargo|jogger|sweatpant)\b', re.I)
_TOP_KW    = re.compile(r'\b(shirt|t-shirt|tee|top|jacket|coat|sweater|hoodie|sweatshirt|outerwear|polo|knitwear|blazer|suit|pullover|knit|button|vest|anorak|parka|overshirt)\b', re.I)


def categorize_product(product: dict) -> str:
    """Return 'top', 'bottom', 'shoe', or 'unknown'."""
    text = ' '.join(filter(None, [
        product.get('product_type', '') or '',
        ' '.join(product.get('tags', []) or []),
        product.get('title', '') or '',
    ]))
    if _SHOE_KW.search(text):   return 'shoe'
    if _BOTTOM_KW.search(text): return 'bottom'
    if _TOP_KW.search(text):    return 'top'
    return 'unknown'


# ---------------------------------------------------------------------------
# Main entry point for Shopify product lists
# ---------------------------------------------------------------------------

def check_products_for_sizes(products: list) -> tuple[list[str], bool]:
    """
    Given a list of Shopify product dicts, return:
      (sorted list of matched size labels available, has_long_option)
    Only available (in-stock) variants are considered.
    """
    matched: set[str] = set()
    has_long = False

    for product in products:
        category = categorize_product(product)

        for variant in product.get('variants', []):
            if not variant.get('available', False):
                continue

            options = [
                (variant.get('option1') or '').strip(),
                (variant.get('option2') or '').strip(),
                (variant.get('option3') or '').strip(),
            ]

            for opt in filter(None, options):
                if category in ('top', 'unknown'):
                    r = match_top_size(opt)
                    if r:
                        matched.add(r)

                if category in ('bottom', 'unknown'):
                    r, long_ = match_bottom_inch_size(opt)
                    if r:
                        matched.add(r)
                        if long_: has_long = True

                    r, long_ = match_bottom_alpha_size(opt)
                    if r:
                        matched.add(r)
                        if long_: has_long = True

                if category in ('shoe', 'unknown'):
                    r = match_shoe_size(opt)
                    if r:
                        matched.add(r)

    return sorted(matched), has_long
