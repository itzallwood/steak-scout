"""
americas_choice_gourmet.py — Scraper for America's Choice Gourmet beef products.

Site: https://americaschoicegourmet.com/product-category/beef/
Platform: WordPress + WooCommerce (static HTML — no Playwright needed)
"""

import logging

from scraper.base_scraper import BaseScraper
from scraper.utils import parse_price, parse_weight

logger = logging.getLogger(__name__)

STORE_NAME = "America's Choice Gourmet"
BEEF_URL = "https://americaschoicegourmet.com/product-category/beef/"


class AmericasChoiceGourmetScraper(BaseScraper):

    def __init__(self):
        super().__init__(store_name=STORE_NAME, base_url=BEEF_URL)

    def scrape(self) -> list[dict]:
        """
        Two-phase scrape:

        Phase 1 — category page(s):
            Walk all paginated pages of /product-category/beef/ and collect
            product name, price, sale price, and detail URL.

        Phase 2 — product detail pages:
            Visit each product URL and extract the description text, then use
            regex to pull out the weight (oz or lb) for that product.

        Splitting into two phases keeps each method focused on one thing and
        makes it easy to test or skip Phase 2 independently.
        """
        # --- Phase 1: collect basic records from category listing ---
        records = []
        url = self.base_url

        while url:
            self.logger.info("Phase 1 — scraping listing page: %s", url)
            soup = self.fetch(url)
            if soup is None:
                break

            items = soup.select("ul.products li.product")
            self.logger.info("Found %d products on this page", len(items))

            for item in items:
                record = self._parse_product(item)
                if record:
                    records.append(record)

            # Follow pagination — WooCommerce uses <a class="next page-numbers">
            next_link = soup.select_one("a.next.page-numbers")
            url = next_link["href"] if next_link else None

            if url:
                self.sleep()

        # --- Phase 2: enrich each record with weight from the detail page ---
        for record in records:
            self.sleep()  # polite delay between detail page requests
            weight_value, weight_unit = self._scrape_weight(record["url"])
            record["weight_value"] = weight_value
            record["weight_unit"] = weight_unit

        self.logger.info("Total products scraped: %d", len(records))
        return records

    def _parse_product(self, item) -> dict | None:
        """
        Extract product data from a single <li> product element.

        Returns None if we can't find a name or any price, so the caller
        can safely skip bad/incomplete listings.
        """
        # The product name lives in an <h2> or <h3> that is wrapped by an <a>,
        # so we grab the heading first, then walk up to the parent <a> for the URL.
        heading = item.select_one("h2, h3")
        if not heading:
            self.logger.warning("Skipping item — no heading found")
            return None

        cut = heading.get_text(strip=True)

        # Product detail URLs follow the pattern /product/product-name/.
        # We find any anchor in the item whose href contains /product/.
        product_a = item.select_one('a[href*="/product/"]')
        product_url = product_a["href"] if product_a else self.base_url

        # WooCommerce price block:
        #   Regular price only  -> <span class="price">$X.XX</span>
        #   On sale             -> <span class="price"><del>$X.XX</del><ins>$X.XX</ins></span>
        price_block = item.select_one("span.price")
        if not price_block:
            self.logger.warning("Skipping '%s' — no price found", cut)
            return None

        sale_tag = price_block.select_one("ins")
        original_tag = price_block.select_one("del")

        if sale_tag:
            # Product is on sale: ins = current sale price, del = original
            price = parse_price(sale_tag.get_text(strip=True))
            sale_price = price  # sale_price = what you pay today
            original_price = parse_price(original_tag.get_text(strip=True)) if original_tag else None
        else:
            # No sale: the whole price block is the regular price
            price = parse_price(price_block.get_text(strip=True))
            sale_price = None
            original_price = None

        return {
            "store": self.store_name,
            "cut": cut,
            "price": price,
            "sale_price": sale_price,
            "original_price": original_price,
            "price_unit": "per_item",  # this site sells by item, not per lb
            "url": product_url,
            # weight fields are filled in during Phase 2
            "weight_value": None,
            "weight_unit": None,
        }

    def _scrape_weight(self, url: str) -> tuple[float | None, str | None]:
        """
        Phase 2: fetch a product detail page and extract the weight.

        WooCommerce detail pages have two places the weight might live:
          1. Short description — a <p> just below the price block, often
             contains "8 oz" or "1.5 lb" inline with the product copy.
          2. Description tab — div.woocommerce-product-details__short-description
             or div#tab-description for longer product descriptions.

        We try the short description first (more reliable), then fall back to
        the full description tab text.
        """
        self.logger.info("Phase 2 — fetching detail page: %s", url)
        soup = self.fetch(url)
        if soup is None:
            return None, None

        # Candidate elements that typically contain weight info, in priority order
        candidates = [
            soup.select_one("div.woocommerce-product-details__short-description"),
            soup.select_one("div#tab-description"),
            soup.select_one("div.woocommerce-tabs"),
        ]

        for element in candidates:
            if element:
                text = element.get_text(" ", strip=True)
                weight_value, weight_unit = parse_weight(text)
                if weight_value:
                    self.logger.info(
                        "Found weight %.1f %s in: %.60s…", weight_value, weight_unit, text
                    )
                    return weight_value, weight_unit

        self.logger.warning("No weight found on detail page: %s", url)
        return None, None
