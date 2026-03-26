"""
americas_choice_gourmet.py — Scraper for America's Choice Gourmet beef products.

Site: https://americaschoicegourmet.com/product-category/beef/
Platform: WordPress + WooCommerce (static HTML — no Playwright needed)
"""

import logging

from scraper.base_scraper import BaseScraper
from scraper.utils import parse_price

logger = logging.getLogger(__name__)

STORE_NAME = "America's Choice Gourmet"
BEEF_URL = "https://americaschoicegourmet.com/product-category/beef/"


class AmericasChoiceGourmetScraper(BaseScraper):

    def __init__(self):
        super().__init__(store_name=STORE_NAME, base_url=BEEF_URL)

    def scrape(self) -> list[dict]:
        """
        Scrape all beef products from the category page.

        WooCommerce renders products as <li> tags inside <ul class="products">.
        We walk every page (following the "next" pagination link) until there
        are no more pages.
        """
        results = []
        url = self.base_url

        while url:
            self.logger.info("Scraping page: %s", url)
            soup = self.fetch(url)
            if soup is None:
                break

            items = soup.select("ul.products li.product")
            self.logger.info("Found %d products on this page", len(items))

            for item in items:
                record = self._parse_product(item)
                if record:
                    results.append(record)

            # Follow pagination — WooCommerce uses <a class="next page-numbers">
            next_link = soup.select_one("a.next.page-numbers")
            url = next_link["href"] if next_link else None

            # Be polite — pause before fetching the next page
            if url:
                self.sleep()

        self.logger.info("Total products scraped: %d", len(results))
        return results

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
            "url": product_url,
        }
