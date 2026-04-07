#!/usr/bin/env python3
"""
Bitcoin Fibonacci Log Chart - Plot Bitcoin price on a log scale with Fibonacci retracement levels and halving dates.

Reads historical price data from a local market-price.json file downloaded from blockchain.com.

Usage:
    python bitcoin_fibonacci_log_chart.py

Notes:
    - Download market-price.json from https://www.blockchain.com/charts/market-price?timespan=all
    - Save the file in the same folder as this script before running.
"""

import os
import json
import datetime as dt

import matplotlib.pyplot as plt
import pandas as pd

# Script and data paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(SCRIPT_DIR, "market-price.json")

# Fibonacci retracement levels (standard levels as decimal fractions)
FIBONACCI_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]

# Bitcoin halving dates (UTC)
HALVING_DATES = [
    dt.datetime(2012, 11, 28),
    dt.datetime(2016, 7, 9),
    dt.datetime(2020, 5, 11),
    dt.datetime(2024, 4, 19),
]

# Plot appearance
FIGURE_WIDTH = 14
FIGURE_HEIGHT = 7
GRID_LINE_WIDTH = 0.5
FIB_LINE_ALPHA = 0.7
HALVING_LINE_ALPHA = 0.6
HALVING_LABEL_FONTSIZE = 8


def main():
    """Load Bitcoin price data, compute Fibonacci levels, and render the chart."""
    if not os.path.exists(JSON_FILE):
        raise FileNotFoundError(
            "\nJSON file not found.\n"
            "To run this script with Bitcoin price data:\n"
            "1. Visit: https://www.blockchain.com/charts/market-price?timespan=all\n"
            "2. Download the JSON file (make sure 'All' is selected as the timespan)\n"
            "3. Save the file as 'market-price.json' in the same folder as this script:\n"
            f"   {SCRIPT_DIR}\n"
            "Then re-run the script."
        )

    print(f"Loading data from: {JSON_FILE}")

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Build DataFrame from raw price data
    price_data = data["market-price"]
    df = pd.DataFrame(price_data)
    df["Date"] = pd.to_datetime(df["x"], unit="ms")
    df["Close"] = df["y"]
    df = df[["Date", "Close"]]
    df = df[df["Close"] > 0]
    df.sort_values("Date", inplace=True)

    # Calculate Fibonacci retracement levels from all-time high/low
    max_price = df["Close"].max()
    min_price = df["Close"].min()
    diff = max_price - min_price
    fib_prices = [max_price - diff * level for level in FIBONACCI_LEVELS]

    # Plot
    plt.figure(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT))
    plt.plot(df["Date"], df["Close"], label="BTC Average Price", color="blue")
    plt.yscale("log")
    plt.title("Bitcoin Price (Log Scale) with Fibonacci Retracement and Halving Events")
    plt.xlabel("Date")
    plt.ylabel("Price (log scale)")
    plt.grid(True, which="both", linestyle="--", linewidth=GRID_LINE_WIDTH)

    for i, price in enumerate(fib_prices):
        plt.axhline(
            y=price,
            linestyle="--",
            alpha=FIB_LINE_ALPHA,
            color="red",
            label=f"Fib {FIBONACCI_LEVELS[i] * 100:.1f}% ({price:.0f} USD)",
        )

    for halving_date in HALVING_DATES:
        if df["Date"].min() <= halving_date <= df["Date"].max():
            plt.axvline(x=halving_date, linestyle=":", color="green", alpha=HALVING_LINE_ALPHA)  # type: ignore[arg-type]
            plt.text(
                halving_date,  # type: ignore[arg-type]
                min_price,
                halving_date.strftime("%Y-%m-%d"),
                rotation=90,
                verticalalignment="bottom",
                fontsize=HALVING_LABEL_FONTSIZE,
                color="green",
            )

    plt.legend()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
