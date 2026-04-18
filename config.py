"""
User size preferences and global configuration.
Edit this file to change your sizes or sale detection thresholds.
"""

# ---------------------------------------------------------------------------
# Size preferences
# ---------------------------------------------------------------------------

USER_SIZES = {
    # Tops: jackets, t-shirts, shirts, outerwear
    "tops": ["L", "XL"],

    # Bottoms with inch sizing (jeans, chinos, trousers)
    "bottoms_inch": {
        "waist": [34, 35],       # Acceptable waist sizes
        "inseam_min": 32.5,      # Minimum inseam in inches
        "inseam_ideal_min": 33,  # Flag "long" at or above this value
    },

    # Bottoms with S/M/L sizing (prefer long cut)
    "bottoms_alpha": ["L"],

    # Shoes
    "shoes_us": [12],
    "shoes_eu": [45, 46],
}

# ---------------------------------------------------------------------------
# Sale detection thresholds
# ---------------------------------------------------------------------------

# Minimum discount % to report when there's no site-wide sale banner
SALE_THRESHOLD_PCT = 25

# ---------------------------------------------------------------------------
# Brand metadata
# ---------------------------------------------------------------------------

# These brands rarely run sales — still monitored but flagged in the notification
LOW_FREQUENCY_BRANDS = {
    "Aime Leon Dore",
    "Noah NYC",
    "Drake's",
    "Percival",
    "Merz B. Schwanen",
}

# ---------------------------------------------------------------------------
# HTTP / scraping config
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 20    # seconds per request
REQUEST_DELAY   = 0.5   # seconds between paginated requests (be polite)
