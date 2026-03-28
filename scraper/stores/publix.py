"""
publix.py — Scraper for Publix steak products.

Site: https://www.publix.com/search?searchTerm=steak&srt=products
Platform: Vue.js SPA — requires Playwright for rendering.

Why Playwright? The site is 100% client-rendered. Product cards only
appear after Vue.js mounts and fetches product data.

Store selection trick:
  Publix requires a store to be set before showing prices. The site reads
  the store from a browser cookie named "Store" (JSON object with a
  StoreNumber field). Without it, the search returns product names but
  no prices.

  We inject the Store cookie into the Playwright context before navigating,
  which causes the Vue.js app to send `PublixStore: 1580` (Ogden Market
  Place) in its product API request headers — unlocking prices.

Strategy:
  1. Inject the "Store" cookie with StoreNumber=1580 (Ogden Market Place)
  2. Navigate to the steak search page
  3. Scroll to trigger lazy-loading of all product cards
  4. Parse name, price, sale price, and URL from each card
"""

import asyncio
import json
import logging
import re
import urllib.parse
from datetime import datetime, timezone

from playwright.async_api import async_playwright

from scraper.utils import parse_price, parse_weight

STORE_NAME = "Publix"
BASE_URL = "https://www.publix.com"
SEARCH_URL = f"{BASE_URL}/search?searchTerm=steak&srt=products"

# Publix Ogden Market Place, Wilmington NC — store number 1580
# To find another store number:
#   GET https://services.publix.com/storelocator/api/v1/stores/?types=R&count=5&distance=20&zip=YOUR_ZIP
DEFAULT_STORE_NUMBER = 1580
DEFAULT_STORE_NAME = "Ogden Market Place"


class PublixScraper:
    """
    Playwright-based scraper for Publix.

    Does NOT inherit from BaseScraper because the requests library cannot
    render the Publix Vue.js SPA. Same pattern as LowesFoodsScraper.

    Key difference from other Playwright scrapers: we inject a "Store"
    cookie before navigating so the Vue.js app sends the store number in
    its product API header, which unlocks price data.
    """

    def __init__(self, store_number: int = DEFAULT_STORE_NUMBER, store_name: str = DEFAULT_STORE_NAME):
        self.store_number = store_number
        self.store_name = store_name
        self.logger = logging.getLogger(self.__class__.__name__)

    def _build_store_cookie(self) -> str:
        """
        Build the value for the "Store" cookie that Publix's Vue.js app reads.

        The app uses a custom cookie library that stores JSON objects as
        URL-encoded strings. The StoreNumber field determines which store's
        prices are shown. Without this cookie, the app defaults to store
        9999 (no store / national view) and no prices are returned.
        """
        store_data = {
            "CreationDate": datetime.now(timezone.utc).isoformat(),
            "Option": "",
            "ShortStoreName": self.store_name,
            "StoreName": self.store_name,
            "StoreNumber": self.store_number,
        }
        # The Publix cookie library URL-encodes the JSON string
        return urllib.parse.quote(json.dumps(store_data))

    def scrape(self) -> list[dict]:
        """
        Synchronous entry point — wraps async scrape so callers don't
        need to manage an event loop.
        """
        return asyncio.run(self._scrape_async())

    async def _scrape_async(self) -> list[dict]:
        """
        Launch a headless Chromium browser, inject the store cookie,
        navigate to the steak search, scroll to load all cards, and
        parse product data from the rendered DOM.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )

            # Inject the Store cookie BEFORE any navigation.
            # The Vue.js app reads this cookie during its initialization
            # to determine which store's prices to fetch. If we set it
            # here, the very first page load will already have the correct
            # store context — no UI interaction needed.
            self.logger.info(
                "Injecting store cookie for store #%d (%s)...",
                self.store_number,
                self.store_name,
            )
            await context.add_cookies([
                {
                    "name": "Store",
                    "value": self._build_store_cookie(),
                    "domain": ".publix.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": False,
                }
            ])

            page = await context.new_page()

            # Navigate to the steak search page
            self.logger.info("Loading search page: %s", SEARCH_URL)
            await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(4000)
            self.logger.info("Page URL: %s", page.url)

            # Wait for product cards to appear
            try:
                await page.wait_for_selector("[class*='product-card']", timeout=15000)
            except Exception:
                self.logger.warning("Product cards not found — store cookie may have expired or selectors changed")
                await browser.close()
                return []

            # Scroll to trigger lazy-loading of all visible products.
            # IMPORTANT: Publix uses virtual scrolling — the DOM only keeps
            # cards near the current viewport. Scrolling down loads new cards
            # but eventually removes ones far above. We collect cards in a
            # running set at each scroll step, deduplicating by product name.
            # We do NOT scroll back to Home at the end — doing so would
            # remove all cards that were loaded partway down the page.
            self.logger.info("Collecting products via scrolling viewport...")
            seen_cuts: set[str] = set()
            all_records: list[dict] = []

            for scroll_pass in range(20):
                # Collect all current cards before scrolling further
                cards_now = await page.query_selector_all("[class*='product-card']")
                new_this_pass = 0
                for card in cards_now:
                    try:
                        first_line = await card.evaluate(
                            "el => el.innerText.split('\\n')[0].trim()"
                        )
                    except Exception:
                        continue
                    if first_line and first_line not in seen_cuts:
                        seen_cuts.add(first_line)
                        record = await self._parse_card(card)
                        if record:
                            all_records.append(record)
                        new_this_pass += 1

                self.logger.debug(
                    "Pass %d: %d new, %d total unique",
                    scroll_pass + 1, new_this_pass, len(seen_cuts)
                )

                if new_this_pass == 0 and scroll_pass >= 2:
                    break  # no new products — we've seen everything

                # Scroll down by one screenful at a time (less aggressive
                # than End key, gives the virtual DOM time to render new cards)
                await page.evaluate("window.scrollBy(0, 800)")
                await page.wait_for_timeout(1800)

            self.logger.info(
                "Collected %d unique products across scroll passes", len(all_records)
            )

            results = [r for r in all_records if self._is_beef_steak(r["cut"])]

            await browser.close()

        self.logger.info("Total steak products kept after filter: %d", len(results))
        return results

    def _is_beef_steak(self, name: str) -> bool:
        """
        Return True only if the product is a fresh beef steak cut.
        """
        name_lower = name.lower()

        cut_keywords = [
            "ribeye", "rib eye", "sirloin", "filet mignon", "tenderloin",
            "new york strip", "ny strip", "strip steak", "t-bone", "t bone",
            "porterhouse", "flank steak", "skirt steak", "flat iron",
            "chuck steak", "cube steak", "round steak", "shaved steak",
            "wagyu", "beef steak", "london broil",
        ]

        skip_keywords = [
            "roast",
            "ham steak", "ham steaks", "tuna", "salmon", "tilapia",
            "shrimp", "chicken", "pork", "lamb", "turkey", "pepperoni",
            "tomato", "tomatoes", "liver",
            "jerky", "tender bites", "patties", "patty", "burger",
            "hamburger", "hot dog", "hotdog", "frank", "wiener", "meatball",
            "ground beef", "ground sirloin", "ground chuck",
            "stew meat", "stew beef", "diced steak", "diced beef",
            "steak strips",
            "dressing", "sauce", "seasoning", "marinade", "soup",
            "burrito", "bowl", "taquito", "roll", "sandwich", "calzone",
            "kabob", "kebab",
            "dog treat", "dog treats", "dog food", "canine", "cat food",
            "feline",
        ]

        if any(skip in name_lower for skip in skip_keywords):
            return False
        return any(kw in name_lower for kw in cut_keywords)

    async def _parse_card(self, card) -> dict | None:
        """
        Extract product data from a single rendered Publix product card.

        Card text format (when store is set and prices are available):
            Ribeye Steak, Boneless, Publix USDA Choice Beef
            $17.99/lb
            Old price: $18.49/lb - Ribeye Steak, ...   ← on sale items only
            Add to list

        Card text format (when on sale — BOGO or percentage off):
            New York Strip Steak Boneless, Publix USDA Choice Beef
            $12.99/lb
            Add to list
        """
        try:
            card_text = await card.inner_text()
        except Exception:
            return None

        if not card_text.strip():
            return None

        lines = [l.strip() for l in card_text.splitlines() if l.strip()]
        if not lines:
            return None

        # Product name is the first line
        cut = lines[0]

        # Build product URL from the card's link
        link = await card.query_selector("a[href*='/pd/']")
        href = await link.get_attribute("href") if link else ""
        product_url = f"{BASE_URL}{href}" if href.startswith("/") else href

        # --- Extract prices ---
        # Primary price: look for "$X.XX/lb" or "$X.XX" pattern
        price_match = re.search(r"\$(\d+\.\d{2})(?:/lb|/oz|/ea)?", card_text)
        if not price_match:
            self.logger.warning("No price found for: %s", cut)
            return None

        price = float(price_match.group(1))
        sale_price = None
        original_price = None

        # Sale indicator: "Old price: $Y.YY/lb" means current price is the sale price
        old_price_match = re.search(r"Old price:\s*\$(\d+\.\d{2})", card_text, re.IGNORECASE)
        if old_price_match:
            original_price = float(old_price_match.group(1))
            sale_price = price

        # --- Extract weight from product name ---
        weight_value, weight_unit = parse_weight(cut)

        # --- Determine price_unit from card text ---
        if "/lb" in card_text:
            price_unit = "per_lb"
        elif "/oz" in card_text:
            price_unit = "per_oz"
        else:
            price_unit = "per_item"

        return {
            "store": STORE_NAME,
            "cut": cut,
            "price": price,
            "sale_price": sale_price,
            "original_price": original_price,
            "price_unit": price_unit,
            "weight_value": weight_value,
            "weight_unit": weight_unit,
            "url": product_url,
        }
