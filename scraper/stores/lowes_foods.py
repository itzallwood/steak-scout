"""
lowes_foods.py — Scraper for Lowe's Foods steak products.

Site: https://shop.lowesfoods.com/search?searchTerms=steak
Platform: React SPA backed by Inmar Falcon API — requires Playwright.

Why Playwright? The site is 100% client-rendered. A plain requests call
returns an empty HTML shell with no product data. We need a real browser
to execute the JavaScript, establish a session, and render the product cards.

Strategy:
  1. Load the homepage so the app can auto-select a store via IP geolocation
  2. Type "steak" in the search box and submit (URL becomes /search?searchTerms=steak)
  3. Wait for product cards to render in the DOM
  4. Parse name, price, sale price, weight, and URL from each card
"""

import asyncio
import logging
import re

from playwright.async_api import async_playwright

from scraper.utils import parse_price, parse_weight

STORE_NAME = "Lowe's Foods"
BASE_URL = "https://shop.lowesfoods.com"
SEARCH_TERM = "steak"


class LowesFoodsScraper:
    """
    Playwright-based scraper for Lowe's Foods.

    Note: This scraper does NOT inherit from BaseScraper because BaseScraper
    uses the requests library which can't render JavaScript. Playwright
    requires async code, so this class manages its own browser session.
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def scrape(self) -> list[dict]:
        """
        Synchronous entry point — wraps the async scrape in asyncio.run()
        so callers don't need to manage an event loop themselves.

        This keeps the interface consistent with the other scrapers, which
        all expose a synchronous scrape() method.
        """
        return asyncio.run(self._scrape_async())

    async def _scrape_async(self) -> list[dict]:
        """
        Launch a headless Chromium browser, search for steaks, and
        scrape all rendered product cards.
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
            page = await context.new_page()

            # Step 1: Load homepage — the app auto-selects a nearby store
            # based on IP geolocation, so no manual store selection is needed
            self.logger.info("Loading homepage to establish store session...")
            await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # Step 2: Use the search box rather than navigating directly to the
            # search URL — the app only fires the search API when the query
            # originates from the search input, not from URL params alone
            self.logger.info("Searching for '%s'...", SEARCH_TERM)
            search_input = await page.wait_for_selector(
                "input[name='search']", timeout=10000
            )
            await search_input.fill(SEARCH_TERM)
            await search_input.press("Enter")

            # Wait for the SPA to finish fetching and rendering products
            await page.wait_for_load_state("networkidle", timeout=30000)
            await page.wait_for_timeout(5000)  # extra buffer for slow renders

            self.logger.info("Page URL: %s", page.url)

            # Step 3: Scrape all rendered product cards
            cards = await page.query_selector_all("[data-test-id='product-card']")
            self.logger.info("Found %d product cards", len(cards))

            results = []
            for card in cards:
                record = await self._parse_card(card)
                if record and self._is_beef_steak(record["cut"]):
                    results.append(record)

            await browser.close()

        self.logger.info("Total products scraped: %d", len(results))
        return results

    def _is_beef_steak(self, name: str) -> bool:
        """
        Return True only if the product is a fresh beef steak cut.

        Strategy: require at least one beef-specific cut keyword AND block
        anything that matches a known non-beef pattern. Using a positive
        allowlist prevents salad dressings, dog food, TV dinners, ham, and
        other "steak"-adjacent products from slipping through.
        """
        name_lower = name.lower()

        # Must contain a real beef cut keyword to pass
        cut_keywords = [
            "ribeye", "rib eye", "sirloin", "filet mignon", "tenderloin",
            "new york strip", "ny strip", "strip steak", "t-bone", "porterhouse",
            "flank steak", "skirt steak", "flat iron", "chuck steak", "cube steak",
            "round steak", "shaved steak", "angus beef", "wagyu", "beef steak",
            "grass fed beef", "grass-fed beef",
        ]

        # Hard blocklist — any match disqualifies the product entirely
        skip_keywords = [
            "ham steak", "ham steaks", "dressing", "sauce", "seasoning", "marinade",
            "soup", "burrito", "bowl", "taquito", "roll", "sandwich", "calzone",
            "dog food", "canine", "cat food", "feline",
            "lean cuisine", "healthy choice", "banquet", "stouffer", "hormel",
            "marie callender", "boston market", "campbells",
            "salisbury", "country fried", "frozen dinner",
            "tuna", "salmon", "tilapia", "shrimp", "chicken", "pork", "lamb",
            "turkey", "pepperoni", "tomato", "tomatoes",
        ]

        if any(skip in name_lower for skip in skip_keywords):
            return False
        return any(kw in name_lower for kw in cut_keywords)

    async def _parse_card(self, card) -> dict | None:
        """
        Extract product data from a single rendered product card element.

        The card's aria-label contains the name, price, and sale/original
        price in a single string. The card text also includes the weight unit
        (e.g. "5oz", "12oz") and unit price (e.g. "$2.00/oz").
        """
        link = await card.query_selector(".c-card__link")
        if not link:
            return None

        aria_label = await link.get_attribute("aria-label") or ""
        href = await link.get_attribute("href") or ""
        product_url = f"{BASE_URL}{href}" if href.startswith("/") else href

        # Full card text gives us price, weight, and name in a clean format
        card_text = await card.inner_text()

        # --- Extract name ---
        # Card text ends with "ADD TO CART"; the product name is the line before it
        lines = [line.strip() for line in card_text.splitlines() if line.strip()]
        try:
            cart_idx = next(i for i, l in enumerate(lines) if "ADD TO CART" in l.upper())
            cut = lines[cart_idx - 1] if cart_idx > 0 else ""
        except StopIteration:
            cut = lines[-1] if lines else ""

        if not cut:
            return None

        # --- Extract prices from aria-label ---
        # Pattern: "priced at $X.XX" (regular) or "discounted price of $X.XX (Originally Priced at $Y.YY)"
        sale_match = re.search(
            r"discounted price of \$([0-9.]+).*Originally Priced at \$([0-9.]+)",
            aria_label,
            re.IGNORECASE,
        )
        regular_match = re.search(r"priced at \$([0-9.]+)", aria_label, re.IGNORECASE)

        if sale_match:
            price = float(sale_match.group(1))
            original_price = float(sale_match.group(2))
            sale_price = price
        elif regular_match:
            price = float(regular_match.group(1))
            original_price = None
            sale_price = None
        else:
            price = parse_price(card_text)
            original_price = None
            sale_price = None

        if price is None:
            self.logger.warning("Could not parse price for: %s", cut)
            return None

        # --- Extract weight from card text ---
        # Weight appears as standalone "5oz" or "12oz" in the price line
        # e.g. "$17.49\n5oz\n($3.50/oz)"
        weight_match = re.search(r"(\d+\.?\d*)\s*(oz|lb)", card_text, re.IGNORECASE)
        if weight_match:
            weight_value = float(weight_match.group(1))
            raw_unit = weight_match.group(2).lower()
            weight_unit = "lb" if raw_unit == "lb" else "oz"
        else:
            weight_value, weight_unit = None, None

        # --- Determine price_unit from card text ---
        # "($X.XX/lb)" -> per_lb, "($X.XX/oz)" -> per_oz, "ea" -> per_item
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
