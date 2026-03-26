"""
base_scraper.py — Abstract base class for all store scrapers.

Every scraper in scraper/stores/ inherits from BaseScraper and must
implement the scrape() method. This enforces a consistent interface so
the agent can call any scraper the same way, regardless of the store.
"""

import logging
import time
from abc import ABC, abstractmethod

import requests
from bs4 import BeautifulSoup

# Module-level logger — each scraper will inherit this or create its own
# child logger (e.g. logging.getLogger(__name__) in the subclass).
logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Abstract base class all store scrapers must inherit from.

    Subclasses must implement scrape(), which returns a list of dicts
    in this shape:
        [{"store": str, "cut": str, "price_per_lb": float, "url": str}]
    """

    # How long to wait between HTTP requests (seconds).
    # Being polite to servers avoids IP bans and is just good practice.
    REQUEST_DELAY = 1.5

    def __init__(self, store_name: str, base_url: str):
        self.store_name = store_name
        self.base_url = base_url

        # Mimic a real browser so servers don't immediately reject the request.
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        # Reuse a single requests.Session so TCP connections are kept alive
        # across multiple requests to the same host — faster and more polite.
        self.session = requests.Session()
        self.session.headers.update(self.headers)

        self.logger = logging.getLogger(self.__class__.__name__)

    def fetch(self, url: str) -> BeautifulSoup | None:
        """
        GET a URL and return a parsed BeautifulSoup object.

        Returns None if the request fails so callers can handle errors
        gracefully instead of crashing.
        """
        self.logger.info("Fetching %s", url)
        try:
            response = self.session.get(url, timeout=10)
            # Raise an exception for 4xx/5xx status codes
            response.raise_for_status()

            # BeautifulSoup parses the raw HTML into a navigable tree.
            # "html.parser" is Python's built-in parser — no extra install needed.
            return BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            self.logger.error("Failed to fetch %s: %s", url, e)
            return None

    def sleep(self):
        """Pause between requests to avoid hammering the server."""
        time.sleep(self.REQUEST_DELAY)

    @abstractmethod
    def scrape(self) -> list[dict]:
        """
        Scrape the store and return a list of price records.

        Each record must be a dict with these keys:
            store       (str)   — store name, e.g. "Main Street Meats"
            cut         (str)   — steak cut, e.g. "ribeye"
            price_per_lb (float) — price in USD per pound
            url         (str)   — page URL where the price was found

        Subclasses must override this method — it's the core contract
        of every scraper.
        """
        ...
