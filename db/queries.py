"""
queries.py — Reusable functions for reading and writing price records.

All functions accept or return plain dicts so the rest of the codebase
doesn't need to import sqlite3 directly.
"""

import logging
from datetime import datetime, timezone

from db.models import get_connection, init_db

logger = logging.getLogger(__name__)


def save_prices(records: list[dict]) -> int:
    """
    Insert a list of scraper result dicts into the prices table.

    Stamps each record with the current UTC time so we know exactly
    when the price was observed. Returns the number of rows inserted.
    """
    if not records:
        return 0

    # Ensure the table exists before we try to write to it
    init_db()

    scraped_at = datetime.now(timezone.utc).isoformat()
    conn = get_connection()

    with conn:
        conn.executemany(
            """
            INSERT INTO prices (store, cut, price, sale_price, original_price, price_unit, weight_value, weight_unit, url, scraped_at)
            VALUES (:store, :cut, :price, :sale_price, :original_price, :price_unit, :weight_value, :weight_unit, :url, :scraped_at)
            """,
            # Merge scraped_at into each record without mutating the originals
            [{**r, "scraped_at": scraped_at} for r in records],
        )

    conn.close()
    logger.info("Saved %d price records (scraped_at=%s)", len(records), scraped_at)
    return len(records)


def get_latest_prices(store: str | None = None) -> list[dict]:
    """
    Return all price records from the most recent scrape session per store.

    "Most recent scrape session" means all rows whose scraped_at matches the
    single latest scraped_at for that store. This ensures that if a product
    was dropped by the scraper in a newer run (e.g. after a filter fix), it
    won't linger in the report from an older run.

    Optionally filter by store name. Results are sorted by price ascending.
    """
    init_db()
    conn = get_connection()

    # Step 1: find the latest scraped_at per store
    # Step 2: return all records from that exact timestamp for each store
    # This means a whole store's latest batch is shown, not stale cuts mixed in.
    query = """
        SELECT p.*
        FROM prices p
        INNER JOIN (
            SELECT store, MAX(scraped_at) AS latest
            FROM prices
            GROUP BY store
        ) latest ON p.store = latest.store
               AND p.scraped_at = latest.latest
        {where}
        ORDER BY p.price ASC
    """

    if store:
        rows = conn.execute(
            query.format(where="WHERE p.store = ?"), (store,)
        ).fetchall()
    else:
        rows = conn.execute(query.format(where="")).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_best_deals(cut: str | None = None) -> list[dict]:
    """
    Return the single cheapest current listing per cut (across all stores).

    Optionally filter to a specific cut name (case-insensitive partial match).
    """
    init_db()
    conn = get_connection()

    query = """
        SELECT p.*
        FROM prices p
        INNER JOIN (
            SELECT store, MAX(scraped_at) AS latest
            FROM prices
            GROUP BY store
        ) latest ON p.store = latest.store
               AND p.scraped_at = latest.latest
        {where}
        ORDER BY p.price ASC
    """

    if cut:
        rows = conn.execute(
            query.format(where="WHERE p.cut LIKE ?"), (f"%{cut}%",)
        ).fetchall()
    else:
        rows = conn.execute(query.format(where="")).fetchall()

    conn.close()
    return [dict(r) for r in rows]
