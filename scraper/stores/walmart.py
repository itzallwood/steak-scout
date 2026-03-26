"""
walmart.py — Scraper for Walmart fresh beef steaks.

Approach: requests + JSON (no Playwright needed).

Walmart builds its pages with Next.js and embeds ALL product data as a JSON
blob inside a <script id="__NEXT_DATA__"> tag. We fetch the HTML, parse out
that script tag, and navigate the JSON to extract products — no browser
rendering required.

Note: Results are location-aware based on the scraping machine's IP address,
so running locally will return inventory/pricing for the nearest Walmart.
"""

import json
import logging
import time

from bs4 import BeautifulSoup

from scraper.base_scraper import BaseScraper
from scraper.utils import parse_price, parse_weight

STORE_NAME = "Walmart"
BASE_URL = "https://www.walmart.com"

# Search queries to run — multiple queries cast a wider net across cuts.
# Results are deduped by (name, price) before saving.
SEARCH_QUERIES = [
    "fresh beef steak",
    "ribeye steak fresh",
    "fresh filet mignon",
    "fresh new york strip steak",
]


class WalmartScraper(BaseScraper):

    def __init__(self):
        # Walmart needs extra headers to pass bot detection checks.
        # These mimic a real Chrome browser more convincingly than defaults.
        super().__init__(store_name=STORE_NAME, base_url=BASE_URL)
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.google.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

    def scrape(self) -> list[dict]:
        """
        Run each search query and collect fresh beef steak products.

        Deduplicates across queries so the same product showing up in multiple
        searches only appears once in the final results.
        """
        seen = set()   # tracks (name, price) pairs to avoid duplicates
        results = []

        for query in SEARCH_QUERIES:
            self.logger.info("Searching: %s", query)
            items = self._fetch_search_results(query)

            for item in items:
                record = self._parse_item(item)
                if record is None:
                    continue

                key = (record["cut"], record["price"])
                if key in seen:
                    continue

                seen.add(key)
                results.append(record)

            # Polite delay between search queries
            time.sleep(2)

        self.logger.info("Total unique products: %d", len(results))
        return results

    def _fetch_search_results(self, query: str) -> list[dict]:
        """
        Fetch a Walmart search page and extract the raw item list from
        the __NEXT_DATA__ JSON blob embedded in the HTML.

        Returns an empty list if the page is blocked or the data path
        doesn't exist (rather than crashing).
        """
        url = f"{BASE_URL}/search?q={query.replace(' ', '+')}"
        soup = self.fetch(url)
        if soup is None:
            return []

        # __NEXT_DATA__ is a <script> tag containing the full page state as JSON.
        # This is a Next.js pattern — the server serialises React props into
        # the HTML so the page can hydrate without a second API call.
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script or not script.string:
            self.logger.warning("No __NEXT_DATA__ found for query: %s", query)
            return []

        try:
            data = json.loads(script.string)
            items = (
                data["props"]["pageProps"]["initialData"]
                    ["searchResult"]["itemStacks"][0]["items"]
            )
            self.logger.info("  Found %d items", len(items))
            return items
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            self.logger.warning("Could not parse __NEXT_DATA__ for '%s': %s", query, e)
            return []

    def _parse_item(self, item: dict) -> dict | None:
        """
        Extract a price record from a single Walmart product dict.

        Only returns records for items priced per lb (fresh meat) or items
        whose name strongly suggests they're fresh steaks. Skips frozen,
        canned, and other non-fresh products.
        """
        name = item.get("name", "")
        if not name:
            return None

        # Skip clearly non-fresh products
        skip_keywords = ["frozen", "canned", "jerky", "stromboli", "salisbury",
                         "country fried", "breaded", "gravy", "tv dinner"]
        if any(kw in name.lower() for kw in skip_keywords):
            return None

        price_info = item.get("priceInfo", {})
        price_per_lb = price_info.get("finalCostByWeight", False)

        # linePriceDisplay is the tray/package price (what you pay at checkout)
        tray_price = parse_price(price_info.get("linePriceDisplay", ""))

        # unitPrice is the per-lb rate, e.g. "$20.97/lb"
        unit_price_raw = price_info.get("unitPrice", "")
        unit_price = parse_price(unit_price_raw)

        if tray_price is None:
            return None

        # Build product URL from the item's SEO path
        canonical_url = item.get("canonicalUrl", "")
        product_url = f"{BASE_URL}{canonical_url}" if canonical_url else BASE_URL

        # Try to extract weight from the product name, e.g. "1.50 - 2.65 lb"
        weight_value, weight_unit = parse_weight(name)

        return {
            "store": self.store_name,
            "cut": name,
            "price": unit_price if price_per_lb else tray_price,
            "sale_price": None,
            "original_price": None,
            "price_unit": "per_lb" if price_per_lb else "per_item",
            "weight_value": weight_value,
            "weight_unit": weight_unit,
            "url": product_url,
        }
