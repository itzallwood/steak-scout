"""
harris_teeter.py — Scraper for Harris Teeter steak products via Kroger API.

Why not Playwright/requests?
  harristeeter.com runs on Kroger's platform protected by Akamai Bot Manager.
  Every request — even from headless Firefox with stealth headers — returns a
  403 Access Denied. Scraping the website directly is not viable.

Why the Kroger Developer API?
  Harris Teeter is a Kroger-owned chain, and Kroger provides a free public API
  at developer.kroger.com that covers all their brands. No bot detection, no
  JavaScript rendering — just authenticated REST calls.

Setup (one-time):
  1. Register a free account at https://developer.kroger.com
  2. Create an application (choose "Confidential" client type)
  3. Add to your .env file:
       KROGER_CLIENT_ID=your_client_id_here
       KROGER_CLIENT_SECRET=your_client_secret_here
       KROGER_LOCATION_ID=01600370  ← Harris Teeter Mayfaire, Wilmington NC

API flow:
  1. POST /connect/oauth2/token → get an access token (expires in 30 min)
  2. GET /products?filter.term=steak&filter.locationId=...  → JSON product list
  3. Parse name, price, promo price, size, and URL from each product

Finding your store's location ID:
  GET /locations?filter.chain=HARRIS-TEETER&filter.zipCode=28405
  This returns a list of nearby Harris Teeter stores with their location IDs.
"""

import logging
import os
import time

import requests
from dotenv import load_dotenv

from scraper.utils import parse_weight

load_dotenv()

STORE_NAME = "Harris Teeter"

# Kroger API endpoints
TOKEN_URL = "https://api.kroger.com/v1/connect/oauth2/token"
PRODUCTS_URL = "https://api.kroger.com/v1/products"
LOCATIONS_URL = "https://api.kroger.com/v1/locations"

# Default location: Harris Teeter Mayfaire, Wilmington NC
# Override via KROGER_LOCATION_ID in .env
DEFAULT_LOCATION_ID = "09700210"  # Harris Teeter Mayfaire, Wilmington NC


class HarrisTeeterscraper:
    """
    API-based scraper for Harris Teeter using the Kroger Developer API.

    Inherits from nothing (not BaseScraper) because we use the requests
    library directly but with OAuth token management — different enough
    from BaseScraper's simple fetch() pattern to warrant its own class.

    Requires KROGER_CLIENT_ID and KROGER_CLIENT_SECRET in .env.
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.client_id = os.getenv("KROGER_CLIENT_ID")
        self.client_secret = os.getenv("KROGER_CLIENT_SECRET")
        self.location_id = os.getenv("KROGER_LOCATION_ID", DEFAULT_LOCATION_ID)

        # Token cache — store the token so we don't re-auth on every product call
        self._access_token: str | None = None
        self._token_expires_at: float = 0

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _get_access_token(self) -> str | None:
        """
        Return a valid access token, refreshing if expired.

        The Kroger API uses OAuth 2.0 Client Credentials flow:
          - We POST our client_id + client_secret to the token endpoint
          - We receive a bearer token that lasts 1800 seconds (30 minutes)
          - We cache it so we're not re-authenticating for every product call
        """
        if not self.client_id or not self.client_secret:
            self.logger.error(
                "Missing KROGER_CLIENT_ID or KROGER_CLIENT_SECRET in .env\n"
                "  Register at https://developer.kroger.com to get credentials."
            )
            return None

        # Return cached token if it's still valid (with a 60-second buffer)
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        self.logger.info("Fetching OAuth token from Kroger API...")
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "scope": "product.compact",
                },
                auth=(self.client_id, self.client_secret),
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            self.logger.error("Token request failed: %s", e)
            return None

        data = resp.json()
        self._access_token = data.get("access_token")
        expires_in = data.get("expires_in", 1800)
        self._token_expires_at = time.time() + expires_in
        self.logger.info("Token acquired (expires in %ds)", expires_in)
        return self._access_token

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def scrape(self) -> list[dict]:
        """
        Fetch all steak products from Harris Teeter via the Kroger Products API.

        The API paginates at 50 items per page, so we loop until we've fetched
        everything. We run multiple search terms to maximize coverage — the API
        returns exact-ish matches, so a single "steak" query may miss some cuts.
        """
        token = self._get_access_token()
        if not token:
            return []

        headers = {"Authorization": f"Bearer {token}"}

        # Use multiple search terms to maximize coverage.
        # The Kroger API doesn't support wildcard queries, so we search for
        # each cut individually to avoid missing products that would come up
        # on "steak" but not on "ribeye" and vice versa.
        search_terms = [
            "beef steak",
            "ribeye steak",
            "sirloin steak",
            "filet mignon",
            "strip steak",
            "t-bone steak",
            "flank steak",
            "skirt steak",
        ]

        seen: set[tuple] = set()  # deduplicate by (name, price)
        results: list[dict] = []

        for term in search_terms:
            self.logger.info("Searching Kroger API for '%s'...", term)
            products = self._fetch_products(term, headers)
            self.logger.info("  → %d raw results", len(products))

            for product in products:
                record = self._parse_product(product)
                if record and self._is_beef_steak(record["cut"]):
                    key = (record["cut"].lower(), record["price"])
                    if key not in seen:
                        seen.add(key)
                        results.append(record)

            # Be polite — add a small delay between search terms
            time.sleep(0.5)

        self.logger.info("Total unique steak products: %d", len(results))
        return results

    def _fetch_products(self, term: str, headers: dict) -> list[dict]:
        """
        Fetch all pages of products matching `term` for our store location.

        The Kroger API paginates via `filter.start` (0-indexed offset) with
        up to 50 results per page. We loop until fewer than 50 are returned.
        """
        products = []
        start = 0
        limit = 50

        # The Kroger API caps results at 300 (offset 0–299 at 50/page = 6 pages).
        # Requesting start=300 returns a 400 — so we stop at 300.
        MAX_OFFSET = 300

        while start < MAX_OFFSET:
            try:
                resp = requests.get(
                    PRODUCTS_URL,
                    headers=headers,
                    params={
                        "filter.term": term,
                        "filter.locationId": self.location_id,
                        "filter.limit": limit,
                        "filter.start": start,
                    },
                    timeout=20,
                )
                resp.raise_for_status()
            except requests.RequestException as e:
                self.logger.warning("API request failed for '%s' at offset %d: %s", term, start, e)
                break

            data = resp.json().get("data", [])
            products.extend(data)

            if len(data) < limit:
                # Fewer than limit returned means this is the last page
                break

            start += limit
            time.sleep(0.25)  # small delay between pages

        return products

    # ------------------------------------------------------------------
    # Product parsing
    # ------------------------------------------------------------------

    def _parse_product(self, product: dict) -> dict | None:
        """
        Convert a Kroger API product object into our standard record format.

        Kroger API product structure (relevant fields):
        {
          "productId": "0001234500000",
          "description": "Harris Teeter Beef Ribeye Steak",
          "items": [
            {
              "itemId": "...",
              "price": {"regular": 14.99, "promo": 11.99},
              "size": "1 LB",
              "soldBy": "WEIGHT"
            }
          ]
        }

        A product can have multiple "items" (size variants). We use the first
        item since Harris Teeter typically lists one size per steak cut.
        """
        cut = product.get("description", "").strip()
        if not cut:
            return None

        # Build product URL — Kroger's web URL uses the productId
        product_id = product.get("productId", "")
        product_url = f"https://www.harristeeter.com/p/{cut.lower().replace(' ', '-')}/{product_id}"

        items = product.get("items", [])
        if not items:
            self.logger.warning("No items array for product: %s", cut)
            return None

        item = items[0]  # use the first (usually only) size variant
        price_data = item.get("price", {})

        # The API distinguishes regular price from promo (sale) price
        regular_price = price_data.get("regular")
        promo_price = price_data.get("promo")

        if regular_price is None:
            self.logger.warning("No price for: %s", cut)
            return None

        # If there's a promo price, it's on sale
        if promo_price and promo_price < regular_price:
            price = promo_price
            sale_price = promo_price
            original_price = regular_price
        else:
            price = regular_price
            sale_price = None
            original_price = None

        # Size comes as a string like "1 LB", "12 OZ", "16 OZ"
        size_str = item.get("size", "")
        weight_value, weight_unit = parse_weight(size_str)
        if not weight_value:
            weight_value, weight_unit = parse_weight(cut)

        # soldBy tells us how the price is expressed
        sold_by = item.get("soldBy", "").upper()
        if sold_by == "WEIGHT":
            price_unit = "per_lb"
        elif sold_by == "UNIT":
            price_unit = "per_item"
        else:
            # Fall back to guessing from the size string
            if weight_unit == "lb" or "lb" in size_str.lower():
                price_unit = "per_lb"
            else:
                price_unit = "per_item"

        return {
            "store": STORE_NAME,
            "cut": cut,
            "price": float(price),
            "sale_price": float(sale_price) if sale_price else None,
            "original_price": float(original_price) if original_price else None,
            "price_unit": price_unit,
            "weight_value": weight_value,
            "weight_unit": weight_unit,
            "url": product_url,
        }

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _is_beef_steak(self, name: str) -> bool:
        """
        Return True only if the product is a fresh beef steak cut.

        Same allowlist + blocklist pattern used in the other scrapers.
        """
        name_lower = name.lower()

        cut_keywords = [
            "ribeye", "rib eye", "sirloin", "filet mignon", "tenderloin",
            "new york strip", "ny strip", "strip steak", "t-bone", "t bone",
            "porterhouse", "flank steak", "skirt steak", "flat iron",
            "chuck steak", "cube steak", "round steak", "shaved steak",
            "wagyu", "beef steak", "london broil",
            # "angus beef" and "grass-fed beef" intentionally omitted —
            # too broad on their own; match things like "Angus Beef Chuck Roast"
        ]

        skip_keywords = [
            # Roasts (not steaks — different cut/cooking method)
            "roast",
            # Other proteins
            "ham steak", "ham steaks", "tuna", "salmon", "tilapia",
            "shrimp", "chicken", "pork", "lamb", "turkey", "pepperoni",
            "tomato", "tomatoes", "liver",
            # Processed / packaged beef products
            "jerky", "tender bites",        # Jack Link's etc.
            "patties", "patty", "burger", "hamburger",
            "hot dog", "hotdog", "frank", "wiener", "meatball",
            "ground beef", "ground sirloin", "ground chuck",
            "stew meat", "stew beef",
            "diced steak", "diced beef",
            "steak strips",                 # stir-fry strips, not a steak cut
            "quicksteak",                   # Gary's QuickSteak frozen product
            # Deli brands (roast beef, not fresh steaks)
            "boar's head",
            # Condiments / meal kits
            "dressing", "sauce", "seasoning", "marinade", "soup",
            "burrito", "bowl", "taquito", "roll", "sandwich", "calzone",
            "kabob", "kebab",
            # Pet food
            "dog treat", "dog treats", "dog food", "canine", "cat food",
            "feline", "pup-peroni",
            # Frozen / prepared meals
            "lean cuisine", "healthy choice", "banquet", "stouffer",
            "hormel", "marie callender", "boston market", "campbells",
            "salisbury", "country fried", "frozen dinner",
        ]

        if any(skip in name_lower for skip in skip_keywords):
            return False
        return any(kw in name_lower for kw in cut_keywords)
