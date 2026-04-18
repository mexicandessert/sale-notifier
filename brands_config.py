"""
Configuration for all Shopify-based brands.

Each entry is passed directly to ShopifyScraper(brand_name, domain, sale_collection, low_frequency).
Add or edit brands here; no scraper code changes needed.
"""

from scrapers.shopify_scraper import ShopifyScraper

# (brand_name, domain, sale_collection, low_frequency)
SHOPIFY_BRAND_CONFIGS = [
    ("Todd Snyder",       "toddsnyder.com",        "sale",    False),
    ("Buck Mason",        "buckmason.com",          "sale",    False),
    ("Aime Leon Dore",    "aimeleondore.com",       "sale",    True),
    ("Percival",          "percivalclo.com",        "sale",    True),
    ("Wax London",        "waxlondon.com",          "sale",    False),
    ("Spier & Mackay",    "spierandmackay.com",     "sale",    False),
    ("Our Legacy",        "ourlegacy.se",           "sale",    False),
    ("Merz B. Schwanen",  "merzbschwanen.com",       "sale",    True),
    ("Alex Mill",         "alexmill.com",           "sale",    False),
    ("Noah NYC",          "noahny.com",             "sale",    True),
    ("NN07",              "nn07.com",               "sale",    False),
    ("Taylor Stitch",     "taylorstitch.com",       "sale",    False),
    ("Faherty",           "fahertybrand.com",       "sale",    False),
    ("GH Bass",           "ghbass.com",             "sale",    False),
    ("Drake's",           "drakes.com",             "sale",    True),
    ("Filson",            "filson.com",             "sale",    False),
]


def build_shopify_scrapers() -> list[ShopifyScraper]:
    return [
        ShopifyScraper(
            brand_name=name,
            domain=domain,
            sale_collection=collection,
            low_frequency=low_freq,
        )
        for name, domain, collection, low_freq in SHOPIFY_BRAND_CONFIGS
    ]
