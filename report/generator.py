"""
generator.py — Builds a self-contained HTML price report from the database.

The output is a single .html file with no external dependencies (all CSS is
inlined) so it opens correctly offline and can be emailed or shared as-is.
"""

import logging
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from db.queries import get_latest_prices

logger = logging.getLogger(__name__)

REPORT_PATH = Path(__file__).resolve().parent.parent / "prices_report.html"


def generate_report(open_in_browser: bool = True) -> Path:
    """
    Pull the latest prices from the database and write prices_report.html.

    Returns the path to the generated file.
    """
    records = get_latest_prices()
    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

    html = _build_html(records, generated_at)
    REPORT_PATH.write_text(html, encoding="utf-8")
    logger.info("Report written to %s", REPORT_PATH)

    if open_in_browser:
        webbrowser.open(REPORT_PATH.as_uri())

    return REPORT_PATH


def _build_html(records: list[dict], generated_at: str) -> str:
    """Render the full HTML string from a list of price record dicts."""

    rows_html = _build_rows(records)
    best_deals_html = _build_best_deals(records)
    count = len(records)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Steak Scout — Price Report</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f5f5f0;
      color: #1a1a1a;
      padding: 2rem;
    }}

    header {{
      max-width: 900px;
      margin: 0 auto 2rem;
    }}

    header h1 {{
      font-size: 2rem;
      font-weight: 700;
      letter-spacing: -0.5px;
    }}

    header h1 span {{ color: #c0392b; }}

    header p {{
      margin-top: 0.4rem;
      color: #666;
      font-size: 0.9rem;
    }}

    section {{
      max-width: 900px;
      margin: 0 auto 2.5rem;
    }}

    section h2 {{
      font-size: 1.1rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #555;
      margin-bottom: 0.75rem;
      padding-bottom: 0.4rem;
      border-bottom: 2px solid #e0e0e0;
    }}

    /* Best deals cards */
    .deals-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 1rem;
    }}

    .deal-card {{
      background: #fff;
      border-radius: 8px;
      padding: 1rem 1.2rem;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      border-left: 4px solid #c0392b;
    }}

    .deal-card .cut {{ font-weight: 600; font-size: 0.95rem; margin-bottom: 0.3rem; }}
    .deal-card .store {{ font-size: 0.8rem; color: #888; margin-bottom: 0.5rem; }}
    .deal-card .price {{ font-size: 1.4rem; font-weight: 700; color: #c0392b; }}
    .deal-card .original {{ font-size: 0.8rem; color: #999; text-decoration: line-through; margin-left: 0.3rem; }}
    .deal-card .savings {{
      display: inline-block;
      margin-top: 0.4rem;
      font-size: 0.75rem;
      background: #fdecea;
      color: #c0392b;
      padding: 0.15rem 0.5rem;
      border-radius: 99px;
      font-weight: 600;
    }}

    /* Price table */
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      font-size: 0.9rem;
    }}

    thead tr {{ background: #1a1a1a; color: #fff; }}
    thead th {{ padding: 0.75rem 1rem; text-align: left; font-weight: 600; }}

    tbody tr {{ border-bottom: 1px solid #f0f0f0; }}
    tbody tr:last-child {{ border-bottom: none; }}
    tbody tr:hover {{ background: #fafafa; }}
    tbody td {{ padding: 0.7rem 1rem; vertical-align: middle; }}

    .price-cell {{ font-weight: 700; color: #c0392b; }}
    .original-price {{ color: #999; text-decoration: line-through; font-size: 0.8rem; margin-left: 0.4rem; font-weight: 400; }}
    .sale-badge {{
      display: inline-block;
      font-size: 0.7rem;
      background: #fdecea;
      color: #c0392b;
      padding: 0.1rem 0.4rem;
      border-radius: 99px;
      font-weight: 600;
      margin-left: 0.4rem;
      vertical-align: middle;
    }}

    a {{ color: #2980b9; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    footer {{
      max-width: 900px;
      margin: 0 auto;
      text-align: center;
      font-size: 0.8rem;
      color: #aaa;
    }}
  </style>
</head>
<body>

<header>
  <h1>🥩 Steak <span>Scout</span></h1>
  <p>Generated {generated_at} &nbsp;·&nbsp; {count} products tracked</p>
</header>

<section>
  <h2>Best Deals Right Now</h2>
  <div class="deals-grid">
    {best_deals_html}
  </div>
</section>

<section>
  <h2>All Prices</h2>
  <table>
    <thead>
      <tr>
        <th>Cut</th>
        <th>Store</th>
        <th>Weight</th>
        <th>Price</th>
        <th>Last Scraped</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</section>

<footer>
  <p>Prices are scraped periodically and may not reflect current in-store pricing.</p>
</footer>

</body>
</html>"""


def _build_rows(records: list[dict]) -> str:
    """Build the <tr> rows for the full price table."""
    if not records:
        return '<tr><td colspan="4" style="text-align:center;color:#999;padding:2rem;">No data yet — run the scraper first.</td></tr>'

    rows = []
    for r in records:
        price = r["price"]
        original = r["original_price"]
        cut = r["cut"]
        store = r["store"]
        url = r["url"] or "#"
        scraped_at = r["scraped_at"][:10]  # just the date portion

        weight_html = (
            f"{r['weight_value']} {r['weight_unit']}"
            if r.get("weight_value") else "—"
        )

        # Show sale badge and strikethrough original if on sale
        if r["sale_price"] and original:
            price_html = (
                f'<span class="price-cell">${price:.2f}</span>'
                f'<span class="original-price">${original:.2f}</span>'
                f'<span class="sale-badge">SALE</span>'
            )
        else:
            price_html = f'<span class="price-cell">${price:.2f}</span>' if price else "—"

        rows.append(f"""
      <tr>
        <td><a href="{url}" target="_blank">{cut}</a></td>
        <td>{store}</td>
        <td>{weight_html}</td>
        <td>{price_html}</td>
        <td>{scraped_at}</td>
      </tr>""")

    return "\n".join(rows)


def _build_best_deals(records: list[dict]) -> str:
    """Build deal cards for the top 6 cheapest products."""
    if not records:
        return ""

    # records are already sorted by price asc from get_latest_prices()
    top = records[:6]
    cards = []
    for r in top:
        price = r["price"]
        original = r["original_price"]
        url = r["url"] or "#"

        original_html = f'<span class="original">${original:.2f}</span>' if original else ""

        savings_html = ""
        if original and price:
            savings = original - price
            savings_html = f'<br><span class="savings">Save ${savings:.2f}</span>'

        cards.append(f"""
    <div class="deal-card">
      <div class="cut"><a href="{url}" target="_blank">{r["cut"]}</a></div>
      <div class="store">{r["store"]}</div>
      <div>
        <span class="price">${price:.2f}</span>{original_html}
        {savings_html}
      </div>
    </div>""")

    return "\n".join(cards)
