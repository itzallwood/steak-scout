"""
utils.py — Shared helper functions used across all scrapers.
"""

import re


def parse_price(text: str) -> float | None:
    """
    Extract a float dollar amount from a messy price string.

    Examples:
        "$12.99"     -> 12.99
        "$1,299.00"  -> 1299.0
        "From $8.00" -> 8.0
        "N/A"        -> None
    """
    if not text:
        return None
    # Strip everything except digits, dots, and commas, then cast to float
    match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    return float(match.group()) if match else None
