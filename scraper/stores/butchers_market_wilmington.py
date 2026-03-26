"""
butchers_market_wilmington.py — Scraper for The Butcher's Market (Wilmington) beef steaks.

Site: https://wilmington.thebutchersmarkets.com/Meat-and-Seafood-Beef-Steaks/
Platform: Custom static e-commerce (NitroSell) — no Playwright needed.

All products load on a single page, so no pagination logic is required.
Pricing is per-item (e.g. "$30.00 / each") — no per-lb pricing on this site.
"""

import logging

from scraper.base_scraper import BaseScraper
from scraper.utils import parse_price, parse_weight

STORE_NAME = "The Butcher's Market (Wilmington)"
BASE_URL = "https://wilmington.thebutchersmarkets.com"
STEAKS_URL = f"{BASE_URL}/Meat-and-Seafood-Beef-Steaks/"


class ButchersMarketWilmingtonScraper(BaseScraper):

    def __init__(self):
        super().__init__(store_name=STORE_NAME, base_url=STEAKS_URL)

    def scrape(self) -> list[dict]:
        """
        Scrape all steak products from the beef steaks category page.

        All products render in a single static page — no pagination needed.
        Each product is identified by an <h5> containing a product link anchor.
        """
        self.logger.info("Fetching steaks page: %s", self.base_url)
        soup = self.fetch(self.base_url)
        if soup is None:
            return []

        # Products are identified by <h5> tags that contain a product link.
        # Walking up to the parent div gives us the full product block with
        # the image, name, price, and URL.
        headings = soup.select("h5")
        self.logger.info("Found %d product headings", len(headings))

        results = []
        for h5 in headings:
            record = self._parse_product(h5)
            if record:
                results.append(record)

        self.logger.info("Total products scraped: %d", len(results))
        return results

    def _parse_product(self, h5) -> dict | None:
        """
        Extract product data from an <h5> heading element and its parent container.

        Returns None if a name or price can't be found.
        """
        # Product name is the text of the anchor inside the <h5>
        name_a = h5.select_one("a")
        if not name_a:
            return None

        cut = name_a.get_text(strip=True)
        if not cut:
            return None

        # Build the absolute product URL from the relative href
        href = name_a.get("href", "")
        product_url = href if href.startswith("http") else f"{BASE_URL}{href}"

        # The price span lives in the same parent container as the <h5>.
        # It contains the dollar amount as text and the unit in a <strong> tag
        # e.g. <span>$30.00 <strong>/ each</strong></span>
        container = h5.parent
        price_span = container.select_one("span") if container else None

        if not price_span:
            self.logger.warning("Skipping '%s' — no price span found", cut)
            return None

        # Extract unit from the <strong> tag, then price from remaining text
        unit_tag = price_span.select_one("strong")
        unit_text = unit_tag.get_text(strip=True).lower() if unit_tag else ""

        # Normalise price_unit: "/ lb" -> "per_lb", anything else -> "per_item"
        price_unit = "per_lb" if "lb" in unit_text else "per_item"

        price = parse_price(price_span.get_text(strip=True))
        if price is None:
            self.logger.warning("Skipping '%s' — could not parse price", cut)
            return None

        # Weight may be embedded in the product name (e.g. "12 oz Filet").
        # parse_weight returns (None, None) if nothing is found — that's fine.
        weight_value, weight_unit = parse_weight(cut)

        return {
            "store": self.store_name,
            "cut": cut,
            "price": price,
            "sale_price": None,       # this site shows one price only
            "original_price": None,
            "price_unit": price_unit,
            "weight_value": weight_value,
            "weight_unit": weight_unit,
            "url": product_url,
        }
