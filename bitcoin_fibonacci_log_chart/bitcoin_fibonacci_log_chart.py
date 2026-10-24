#!/usr/bin/env python3
"""
Bitcoin Fibonacci Log Chart - Plot Bitcoin price on a log scale with Fibonacci retracement levels and halving dates.

Reads historical price data from a local market-price.json file from blockchain.com.
When the file is missing or was not updated today, the script offers to download it.

Usage:
    python bitcoin_fibonacci_log_chart.py

Notes:
    - A manual export from https://www.blockchain.com/charts/market-price?timespan=all
      saved as market-price.json next to this script works too.
    - A downloaded file is converted to the same format as the manual export.
"""

import contextlib
import http.client
import os
import json
import sys
import tempfile
import urllib.error
import urllib.request
import datetime as dt
from typing import Any, NoReturn, cast

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

# Path argument accepted by the file helpers
PathArg = str | os.PathLike[str]

# Script and data paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(SCRIPT_DIR, "market-price.json")
TEMP_FILE_SUFFIX = ".tmp"

# Keys of the blockchain.com export
DATA_KEY = "market-price"
TIMESTAMP_KEY = "x"
PRICE_KEY = "y"

# Download settings and keys of the blockchain.com API response
DATA_URL = (
    "https://api.blockchain.info/charts/market-price"
    "?timespan=all&format=json&sampled=false"
)
USER_AGENT = "Mozilla/5.0 (compatible; bitcoin-fibonacci-log-chart)"
DOWNLOAD_TIMEOUT_SECONDS = 30
BYTES_PER_MB = 1024 * 1024
MAX_DOWNLOAD_BYTES = 50 * BYTES_PER_MB
API_STATUS_KEY = "status"
API_STATUS_OK = "ok"
API_VALUES_KEY = "values"
MS_PER_SECOND = 1000

# Prompt handling and exit codes
YES_ANSWERS = ("y", "yes")
EXIT_FAILURE = 1

# Fibonacci retracement levels (standard levels as decimal fractions)
FIBONACCI_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]

# Bitcoin halving dates (UTC)
HALVING_DATES = [
    dt.datetime(2012, 11, 28),
    dt.datetime(2016, 7, 9),
    dt.datetime(2020, 5, 11),
    dt.datetime(2024, 4, 20),
]

# Plot appearance
FIGURE_WIDTH = 14
FIGURE_HEIGHT = 7
GRID_LINE_WIDTH = 0.5
FIB_LINE_ALPHA = 0.7
HALVING_LINE_ALPHA = 0.6
HALVING_LABEL_FONTSIZE = 8
PERCENT_MULTIPLIER = 100


def load_price_data(json_file: PathArg) -> pd.DataFrame:
    """
    Load the blockchain.com export into a DataFrame with Date and Close columns.

    Rows with a missing or non-positive price are dropped (the export starts with
    zero prices, which cannot be drawn on a log scale). The result is sorted by date.

    Raises:
        FileNotFoundError: json_file does not exist.
        ValueError: the file is not valid JSON, lacks the price series, or holds
            no positive prices.
    """
    with open(json_file, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{json_file} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get(DATA_KEY), list):
        raise ValueError(f"{json_file} has no '{DATA_KEY}' price series")

    df = pd.DataFrame(data[DATA_KEY])
    if TIMESTAMP_KEY not in df.columns or PRICE_KEY not in df.columns:
        raise ValueError(
            f"{json_file} price entries need '{TIMESTAMP_KEY}' and '{PRICE_KEY}' fields"
        )

    timestamps = pd.Series(pd.to_numeric(df[TIMESTAMP_KEY], errors="coerce"))
    prices = pd.Series(pd.to_numeric(df[PRICE_KEY], errors="coerce"))
    frame = pd.DataFrame({"Date": pd.to_datetime(timestamps, unit="ms"), "Close": prices})
    frame = frame.dropna()
    positive = pd.DataFrame(frame[frame["Close"] > 0])
    df = positive.sort_values(by="Date").reset_index(drop=True)

    if df.empty:
        raise ValueError(f"{json_file} contains no positive prices")
    return df


def compute_fibonacci_prices(
    max_price: float, min_price: float, levels: list[float] | None = None
) -> list[float]:
    """Return the retracement price for each level, measured down from max_price."""
    if levels is None:
        levels = FIBONACCI_LEVELS
    diff = max_price - min_price
    return [max_price - diff * level for level in levels]


def halvings_in_range(
    first_date: dt.datetime,
    last_date: dt.datetime,
    halving_dates: list[dt.datetime] | None = None,
) -> list[dt.datetime]:
    """Return the halving dates that fall within [first_date, last_date]."""
    if halving_dates is None:
        halving_dates = HALVING_DATES
    return [d for d in halving_dates if first_date <= d <= last_date]


def build_chart(df: pd.DataFrame) -> Figure:
    """Draw the log-scale price chart with Fibonacci levels and halvings."""
    max_price = cast(float, df["Close"].max())
    min_price = cast(float, df["Close"].min())
    fib_prices = compute_fibonacci_prices(max_price, min_price)

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT))
    ax.plot(df["Date"], df["Close"], label="BTC Average Price", color="blue")
    ax.set_yscale("log")
    ax.set_title("Bitcoin Price (Log Scale) with Fibonacci Retracement and Halving Events")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price (log scale)")
    ax.grid(True, which="both", linestyle="--", linewidth=GRID_LINE_WIDTH)

    for level, price in zip(FIBONACCI_LEVELS, fib_prices):
        ax.axhline(
            y=price,
            linestyle="--",
            alpha=FIB_LINE_ALPHA,
            color="red",
            label=f"Fib {level * PERCENT_MULTIPLIER:.1f}% ({price:.0f} USD)",
        )

    first_date = cast(dt.datetime, df["Date"].min())
    last_date = cast(dt.datetime, df["Date"].max())
    for halving_date in halvings_in_range(first_date, last_date):
        ax.axvline(x=halving_date, linestyle=":", color="green", alpha=HALVING_LINE_ALPHA)  # type: ignore[arg-type]
        ax.text(
            halving_date,  # type: ignore[arg-type]
            min_price,
            halving_date.strftime("%Y-%m-%d"),
            rotation=90,
            verticalalignment="bottom",
            fontsize=HALVING_LABEL_FONTSIZE,
            color="green",
        )

    ax.legend()
    fig.tight_layout()
    return fig


def is_data_current(json_file: PathArg) -> bool:
    """Return True if json_file exists and was last modified today (local date)."""
    if not os.path.exists(json_file):
        return False
    modified = dt.datetime.fromtimestamp(os.path.getmtime(json_file)).date()
    return modified == dt.date.today()


def convert_api_response(payload: object) -> dict[str, list[dict[str, Any]]]:
    """
    Convert a blockchain.com API response to the on-disk export format.

    The API reports timestamps in seconds; the export (and load_price_data)
    uses milliseconds under the 'market-price' key.

    Raises:
        ValueError: the status is not ok or the values are missing or malformed.
    """
    if not isinstance(payload, dict) or payload.get(API_STATUS_KEY) != API_STATUS_OK:
        raise ValueError("the server did not return a successful price response")
    values = payload.get(API_VALUES_KEY)
    if not isinstance(values, list) or not values:
        raise ValueError(f"the server response has no '{API_VALUES_KEY}' price series")
    try:
        points = [_convert_entry(entry) for entry in values]
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("the server response has malformed price entries") from exc
    return {DATA_KEY: points}


def _convert_entry(entry: Any) -> dict[str, Any]:
    """
    Convert one API point (seconds) to an export point (milliseconds).

    Raises:
        KeyError, TypeError, ValueError, OverflowError: the point is malformed
            (missing field, non-numeric timestamp, NaN or infinite timestamp).
    """
    seconds = entry[TIMESTAMP_KEY]
    # A string would be repeated by '*' instead of scaled; bool is an int subclass
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise TypeError("timestamp must be a number")
    return {
        TIMESTAMP_KEY: int(seconds * MS_PER_SECOND),
        PRICE_KEY: entry[PRICE_KEY],
    }


def _fetch_bytes(url: str) -> bytes:
    """
    Fetch url and return the body, reading at most MAX_DOWNLOAD_BYTES.

    Raises:
        ConnectionError: the request failed (network, timeout, HTTP or protocol error).
        ValueError: the body exceeds MAX_DOWNLOAD_BYTES.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
            # One extra byte tells an oversized body from one exactly at the cap
            raw = resp.read(MAX_DOWNLOAD_BYTES + 1)
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        raise ConnectionError(f"could not download the price data: {exc}") from exc
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"the server response exceeds {MAX_DOWNLOAD_BYTES // BYTES_PER_MB} MB"
        )
    return raw


def _write_validated(converted: dict[str, Any], json_file: PathArg) -> None:
    """
    Write converted to a temp file, validate it with load_price_data, then
    atomically replace json_file. The temp file is removed on any failure.

    Raises:
        ValueError: the data holds no usable positive prices.
    """
    folder = os.path.dirname(os.path.abspath(json_file))
    fd, temp_path = tempfile.mkstemp(dir=folder, suffix=TEMP_FILE_SUFFIX)
    try:
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            json.dump(converted, handle)
        try:
            load_price_data(temp_path)
        except ValueError as exc:
            raise ValueError(f"the downloaded data is unusable: {exc}") from exc
        os.replace(temp_path, json_file)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(temp_path)
        raise


def download_price_data(json_file: PathArg, url: str = DATA_URL) -> None:
    """
    Download the full price history and write it to json_file atomically.

    The data goes to a temp file in the same folder first, is checked with
    load_price_data, and replaces json_file only when usable, so a failed or
    empty download never corrupts an existing file.

    Raises:
        ConnectionError: the request failed (network, timeout or HTTP error).
        ValueError: the response is too large, not valid JSON, or lacks usable prices.
    """
    raw = _fetch_bytes(url)
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"the server response is not valid JSON: {exc}") from exc
    _write_validated(convert_api_response(payload), json_file)


def ask_yes_no(question: str) -> bool:
    """Ask a yes/no question on the console; default is No (also on EOF or Ctrl+C)."""
    try:
        answer = input(question)
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in YES_ANSWERS


def manual_download_instructions() -> str:
    """Return the text explaining how to obtain market-price.json by hand."""
    return (
        "\nTo run this script with Bitcoin price data:\n"
        "1. Visit: https://www.blockchain.com/charts/market-price?timespan=all\n"
        "2. Download the JSON file (make sure 'All' is selected as the timespan)\n"
        "3. Save the file as 'market-price.json' in the same folder as this script:\n"
        f"   {SCRIPT_DIR}\n"
        "Then re-run the script."
    )


def fail(message: str) -> NoReturn:
    """Print message to stderr and exit with a failure code (no traceback)."""
    print(message, file=sys.stderr)
    raise SystemExit(EXIT_FAILURE)


def ensure_price_data(json_file: PathArg) -> None:
    """
    Make sure json_file is usable, offering to download it when missing or stale.

    A stale file is kept if the user declines or the download fails. A missing
    file with no successful download ends the program with the manual instructions.
    """
    has_file = os.path.exists(json_file)
    if has_file and is_data_current(json_file):
        return

    if has_file:
        question = "Price data was not updated today. Download it now? [y/N] "
    else:
        question = f"Price data file not found ({json_file}). Download it now? [y/N] "

    if not ask_yes_no(question):
        if not has_file:
            fail(manual_download_instructions())
        return

    try:
        print(f"Downloading price data to: {json_file}")
        download_price_data(json_file)
    except (ConnectionError, ValueError, OSError) as exc:
        if has_file:
            print(f"Warning: {exc}. Using the existing file.", file=sys.stderr)
            return
        fail(f"Error: {exc}\n{manual_download_instructions()}")


def load_or_repair(json_file: PathArg) -> pd.DataFrame:
    """
    Load json_file; if its content is unusable, offer to download a fresh copy.

    Exits with the error and a delete-or-replace hint when the user declines or
    the download fails.
    """
    try:
        return load_price_data(json_file)
    except OSError as exc:
        fail(f"Error: {exc}")
    except ValueError as exc:
        error = exc

    hint = f"Delete or replace {json_file} and re-run the script."
    if not ask_yes_no(f"Error: {error}\nDownload a fresh copy now? [y/N] "):
        fail(f"Error: {error}\n{hint}")
    try:
        print(f"Downloading price data to: {json_file}")
        download_price_data(json_file)
        return load_price_data(json_file)
    except (ConnectionError, ValueError, OSError) as exc:
        fail(f"Error: {exc}\n{hint}")


def main() -> None:
    """Load Bitcoin price data, compute Fibonacci levels, and render the chart."""
    ensure_price_data(JSON_FILE)

    print(f"Loading data from: {JSON_FILE}")
    df = load_or_repair(JSON_FILE)
    try:
        build_chart(df)
    except (ValueError, OSError) as exc:
        fail(f"Error: {exc}")
    plt.show()


if __name__ == "__main__":
    main()
