#!/usr/bin/env python3
"""
Bitcoin Price Models - Interactive Bitcoin price chart with Golden Ratio and Power Law models.

Writes a self-contained HTML page (output/chart.html) and opens it in the browser.
It has two switchable views: Philip Swift's Golden Ratio Multiplier (350-day moving
average and bands at 1.6, 2, 3 and 5 times it) and a Power Law fair value with Rainbow
bands, both with era highs and halving dates.

Reads historical price data from data/market-price.json (blockchain.com format).
When the file is missing or was not updated today, the tool offers to download it.

Usage:
    python main.py
    python main.py --mode powerlaw --no-open

Notes:
    - A manual export from https://www.blockchain.com/charts/market-price?timespan=all
      saved as data/market-price.json works too.
    - The chart library and the halving dates are downloaded on first use and cached.
"""

import argparse

from chart_html import open_chart, render_chart, write_chart
from chart_payload import build_payload
from config import (
    CHART_FILE,
    CHART_SCRIPT,
    CHART_TEMPLATE,
    DEFAULT_MODE,
    HALVINGS_FILE,
    JSON_FILE,
    LWC_FILE,
    MODES,
    OPEN_BROWSER,
)
from halvings import ensure_halvings, load_halvings
from lib_cache import ensure_chart_library
from price_data import ensure_price_data, load_or_repair
from utils import fail, logger


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Interactive Bitcoin price chart with Golden Ratio and Power Law models."
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default=DEFAULT_MODE,
        help=f"view shown first (default: {DEFAULT_MODE})",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="write the chart but do not open it in the browser",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Load the data, build the chart page, write it and open it in the browser."""
    args = parse_args(argv)
    # The halvings refresh together with the price data, on the same answer
    refresh = ensure_price_data(JSON_FILE)
    ensure_halvings(HALVINGS_FILE, refresh)
    ensure_chart_library(LWC_FILE)

    logger.log_info(f"Loading data from: {JSON_FILE}")
    df = load_or_repair(JSON_FILE)
    try:
        payload = build_payload(df, load_halvings(HALVINGS_FILE), args.mode)
        page = render_chart(payload, CHART_TEMPLATE, CHART_SCRIPT, LWC_FILE)
        write_chart(page, CHART_FILE)
    except (ValueError, OSError) as exc:
        fail(str(exc))
    if OPEN_BROWSER and not args.no_open and not open_chart(CHART_FILE):
        logger.log_warning("No web browser could be opened; open the file by hand.")
    logger.log_info(f"Chart written to: {CHART_FILE}")


if __name__ == "__main__":
    main()
