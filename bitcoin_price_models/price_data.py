#!/usr/bin/env python3
"""
Price data: load the blockchain.com export, download it and keep the file usable.
"""

import datetime as dt
import json
import os
from typing import Any

import pandas as pd

from config import (
    API_STATUS_KEY,
    API_STATUS_OK,
    API_VALUES_KEY,
    CLOSE_COLUMN,
    DATA_DIR,
    DATA_KEY,
    DATA_URL,
    DATE_COLUMN,
    MS_PER_SECOND,
    PRICE_KEY,
    TIMESTAMP_KEY,
)
from utils import PathArg, ask_yes_no, fail, fetch_bytes, logger, write_validated


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
    frame = pd.DataFrame(
        {DATE_COLUMN: pd.to_datetime(timestamps, unit="ms"), CLOSE_COLUMN: prices}
    )
    frame = frame.dropna()
    positive = pd.DataFrame(frame[frame[CLOSE_COLUMN] > 0])
    df = positive.sort_values(by=DATE_COLUMN).reset_index(drop=True)

    if df.empty:
        raise ValueError(f"{json_file} contains no positive prices")
    return df


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
    raw = fetch_bytes(url)
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"the server response is not valid JSON: {exc}") from exc
    write_validated(convert_api_response(payload), json_file, load_price_data)


def manual_download_instructions() -> str:
    """Return the text explaining how to obtain market-price.json by hand."""
    return (
        "\nTo run this script with Bitcoin price data:\n"
        "1. Visit: https://www.blockchain.com/charts/market-price?timespan=all\n"
        "2. Download the JSON file (make sure 'All' is selected as the timespan)\n"
        "3. Save the file as 'market-price.json' in this folder:\n"
        f"   {DATA_DIR}\n"
        "Then re-run the script."
    )


def ensure_price_data(json_file: PathArg) -> bool:
    """
    Make sure json_file is usable, offering to download it when missing or stale.

    A stale file is kept if the user declines or the download fails. A missing
    file with no successful download ends the program with the manual instructions.

    Returns:
        True if the user agreed to download (so other data can refresh with it),
        False if the file was current or the user declined.
    """
    has_file = os.path.exists(json_file)
    if has_file and is_data_current(json_file):
        return False

    if has_file:
        question = "Price data was not updated today. Download it now? [y/N] "
    else:
        question = f"Price data file not found ({json_file}). Download it now? [y/N] "

    if not ask_yes_no(question):
        if not has_file:
            fail(f"Price data file not found.{manual_download_instructions()}")
        return False

    try:
        logger.log_info(f"Downloading price data to: {json_file}")
        download_price_data(json_file)
    except (ConnectionError, ValueError, OSError) as exc:
        if not has_file:
            fail(f"{exc}\n{manual_download_instructions()}")
        logger.log_warning(f"{exc}. Using the existing file.")
    return True


def load_or_repair(json_file: PathArg) -> pd.DataFrame:
    """
    Load json_file; if its content is unusable, offer to download a fresh copy.

    Exits with the error and a delete-or-replace hint when the user declines or
    the download fails.
    """
    try:
        return load_price_data(json_file)
    except OSError as exc:
        fail(str(exc))
    except ValueError as exc:
        error = exc

    hint = f"Delete or replace {json_file} and re-run the script."
    if not ask_yes_no(f"Error: {error}\nDownload a fresh copy now? [y/N] "):
        fail(f"{error}\n{hint}")
    try:
        logger.log_info(f"Downloading price data to: {json_file}")
        download_price_data(json_file)
        return load_price_data(json_file)
    except (ConnectionError, ValueError, OSError) as exc:
        fail(f"{exc}\n{hint}")
