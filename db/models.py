"""
models.py — Database schema and setup for steak-scout.

We use Python's built-in sqlite3 module — no extra dependencies needed.
The database is a single file at data/prices.db.
"""

import sqlite3
from pathlib import Path

# Resolve the db path relative to this file so it works from any working directory
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "prices.db"


def get_connection() -> sqlite3.Connection:
    """
    Open and return a connection to the SQLite database.

    detect_types lets sqlite3 automatically convert stored TEXT values back
    to Python types (like datetime) when we read them out.
    """
    DB_PATH.parent.mkdir(exist_ok=True)  # ensure data/ directory exists
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    # Row factory lets us access columns by name (row["cut"]) instead of index
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """
    Create the prices table if it doesn't already exist.

    We never drop or recreate the table — every scrape appends new rows so
    we build up a price history over time.
    """
    conn = get_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                store          TEXT    NOT NULL,
                cut            TEXT    NOT NULL,
                price          REAL,
                sale_price     REAL,
                original_price REAL,
                url            TEXT,
                scraped_at     TEXT    NOT NULL  -- ISO 8601 timestamp, e.g. 2026-03-26T14:00:00
            )
        """)
    conn.close()
