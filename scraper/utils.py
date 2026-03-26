"""
utils.py — Shared helper functions used across all scrapers.
"""

import re


def parse_weight(text: str) -> tuple[float | None, str | None]:
    """
    Extract a weight value and unit from a product description string.

    Returns a (value, unit) tuple, or (None, None) if no weight is found.

    Examples:
        "8 oz filet"          -> (8.0, "oz")
        "1.5 lb ribeye"       -> (1.5, "lb")
        "Two 12 ounce steaks" -> (12.0, "oz")
        "No weight here"      -> (None, None)
    """
    match = re.search(
        r"(\d+\.?\d*)\s*(oz|lb|lbs|ounce|ounces|pound|pounds)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, None

    value = float(match.group(1))
    # Normalize unit to either "oz" or "lb" for consistency across scrapers
    raw_unit = match.group(2).lower()
    unit = "lb" if raw_unit in ("lb", "lbs", "pound", "pounds") else "oz"
    return value, unit


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
