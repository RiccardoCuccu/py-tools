#!/usr/bin/env python3
"""
Halvings: fetch past halving dates from mempool.space, cache them and estimate the next.
"""

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from config import (
    BLOCK_TIME_SECONDS,
    BLOCK_TIMESTAMP_KEY,
    COMPUTED_AT_KEY,
    ESTIMATED_TIMESTAMP_KEY,
    HALVING_INTERVAL_BLOCKS,
    HALVINGS_NEXT_KEY,
    HALVINGS_PAST_KEY,
    HEIGHT_KEY,
    MAX_PLAUSIBLE_TIMESTAMP,
    MAX_TIP_HEIGHT,
    MEMPOOL_BLOCK_URL,
    MEMPOOL_TIP_HEIGHT_URL,
    MIN_BLOCK_TIMESTAMP,
    TIP_HEIGHT_KEY,
)
from utils import PathArg, fetch_bytes, logger, write_validated


@dataclass
class HalvingInfo:
    """Past halving dates and the estimated next one, as naive UTC datetimes."""

    past: list[dt.datetime]
    next_estimate: dt.datetime | None


def _check_timestamp(value: object, what: str) -> int:
    """Return value if it is an int unix timestamp in the plausible range."""
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not MIN_BLOCK_TIMESTAMP <= value <= MAX_PLAUSIBLE_TIMESTAMP
    ):
        raise ValueError(f"{what} is not a plausible timestamp: {value!r}")
    return value


def _is_int(value: object) -> bool:
    """Return True for a real int; bool is an int subclass but never valid here."""
    return isinstance(value, int) and not isinstance(value, bool)


def _check_height(value: object, what: str) -> int:
    """Return value if it is a non-negative int block height within the sane bound."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{what} is not an integer: {value!r}")
    if not 0 <= value <= MAX_TIP_HEIGHT:
        raise ValueError(f"{what} is out of range: {value}")
    return value


def _check_halving_height(value: object, what: str) -> int:
    """Return value if it is a positive multiple of the halving interval."""
    height = _check_height(value, what)
    if height == 0 or height % HALVING_INTERVAL_BLOCKS:
        raise ValueError(f"{what} is not a halving height: {height}")
    return height


def halving_heights(tip_height: int) -> list[int]:
    """Return every halving height at or below tip_height, ascending."""
    count = tip_height // HALVING_INTERVAL_BLOCKS
    return [k * HALVING_INTERVAL_BLOCKS for k in range(1, count + 1)]


def next_halving_height(tip_height: int) -> int:
    """Return the first halving height above tip_height."""
    return (tip_height // HALVING_INTERVAL_BLOCKS + 1) * HALVING_INTERVAL_BLOCKS


def estimate_next_halving(tip_height: int, now: dt.datetime) -> dict[str, int]:
    """
    Estimate the next halving as now plus the remaining blocks at the target block time.

    Returns the cache record: height, estimated_timestamp, tip_height, computed_at.
    """
    now_ts = int(now.timestamp())
    height = next_halving_height(tip_height)
    return {
        HEIGHT_KEY: height,
        ESTIMATED_TIMESTAMP_KEY: now_ts + (height - tip_height) * BLOCK_TIME_SECONDS,
        TIP_HEIGHT_KEY: tip_height,
        COMPUTED_AT_KEY: now_ts,
    }


def _to_datetime(timestamp: int) -> dt.datetime:
    """Convert a unix timestamp to a naive UTC datetime (like the price dates)."""
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).replace(tzinfo=None)


def _parse_cache(
    data: object, source: PathArg
) -> tuple[dict[int, int], dict[str, int]]:
    """
    Validate decoded cache content.

    Returns the past halvings as {height: timestamp} and the next-halving record.

    Raises:
        ValueError: the structure, types, heights or timestamps are not usable.
    """
    if not isinstance(data, dict):
        raise ValueError(f"{source} is not a halvings cache")
    entries = data.get(HALVINGS_PAST_KEY)
    record = data.get(HALVINGS_NEXT_KEY)
    if not isinstance(entries, list) or not isinstance(record, dict):
        raise ValueError(
            f"{source} lacks the '{HALVINGS_PAST_KEY}' or '{HALVINGS_NEXT_KEY}' section"
        )

    past: dict[int, int] = {}
    previous_height = 0
    previous_timestamp = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{source} has a malformed halving entry")
        height = _check_halving_height(entry.get(HEIGHT_KEY), "halving height")
        timestamp = _check_timestamp(entry.get(BLOCK_TIMESTAMP_KEY), "halving time")
        if height <= previous_height or timestamp <= previous_timestamp:
            raise ValueError(f"{source} halvings are not in ascending order")
        past[height] = timestamp
        previous_height, previous_timestamp = height, timestamp

    tip = _check_height(record.get(TIP_HEIGHT_KEY), "tip height")
    height = _check_halving_height(record.get(HEIGHT_KEY), "next halving height")
    if height != next_halving_height(tip):
        raise ValueError(f"{source} next halving does not follow the tip height")
    if list(past) != halving_heights(tip):
        raise ValueError(f"{source} past halvings do not match the tip height")
    nxt = {
        HEIGHT_KEY: height,
        TIP_HEIGHT_KEY: tip,
        ESTIMATED_TIMESTAMP_KEY: _check_timestamp(
            record.get(ESTIMATED_TIMESTAMP_KEY), "estimated halving time"
        ),
        COMPUTED_AT_KEY: _check_timestamp(record.get(COMPUTED_AT_KEY), "computed_at"),
    }
    return past, nxt


def _read_cache(json_file: PathArg) -> tuple[dict[int, int], dict[str, int]]:
    """
    Read and validate the halvings cache.

    Raises:
        FileNotFoundError, OSError: the file cannot be read.
        ValueError: the file is not valid JSON or not a usable cache.
    """
    with open(json_file, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{json_file} is not valid JSON: {exc}") from exc
    return _parse_cache(data, json_file)


def load_halvings(json_file: PathArg) -> HalvingInfo:
    """
    Load the halvings cache; return an empty HalvingInfo when it is missing or unusable.

    An unreadable or invalid cache is reported as a warning, never raised, so the
    chart can always be drawn.
    """
    try:
        past, nxt = _read_cache(json_file)
    except FileNotFoundError:
        return HalvingInfo(past=[], next_estimate=None)
    except (OSError, ValueError) as exc:
        logger.log_warning(f"Ignoring the halvings cache: {exc}")
        return HalvingInfo(past=[], next_estimate=None)
    return HalvingInfo(
        past=[_to_datetime(ts) for ts in past.values()],
        next_estimate=_to_datetime(nxt[ESTIMATED_TIMESTAMP_KEY]),
    )


def fetch_tip_height() -> int:
    """
    Fetch the current chain tip height from mempool.space.

    Raises:
        ConnectionError: the request failed.
        ValueError: the response is not a plain non-negative integer in range.
    """
    text = fetch_bytes(MEMPOOL_TIP_HEIGHT_URL).decode("ascii", errors="replace").strip()
    if not (text.isascii() and text.isdigit()):
        raise ValueError(f"the tip height response is not an integer: {text[:40]!r}")
    return _check_height(int(text), "tip height")


def fetch_block_timestamp(height: int) -> int:
    """
    Fetch the timestamp (unix seconds) of the block at height from mempool.space.

    Raises:
        ConnectionError: the request failed.
        ValueError: the response is not JSON, is for another block or has no
            plausible timestamp.
    """
    raw = fetch_bytes(MEMPOOL_BLOCK_URL.format(height=height))
    try:
        payload: Any = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"the block {height} response is not valid JSON: {exc}") from exc
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ValueError(f"the block {height} response is malformed")
    block = payload[0]
    if not _is_int(block.get(HEIGHT_KEY)) or block[HEIGHT_KEY] != height:
        raise ValueError(f"the response is not for block {height}")
    return _check_timestamp(block.get(BLOCK_TIMESTAMP_KEY), f"block {height} time")


def update_halvings(json_file: PathArg, now: dt.datetime | None = None) -> None:
    """
    Refresh json_file: fetch only the missing past halvings and re-estimate the next.

    Past halvings never change, so heights already in a usable cache are kept.
    The result is validated and replaces json_file atomically.

    Raises:
        ConnectionError: a request failed.
        ValueError: a response or the resulting cache is unusable.
        OSError: the cache cannot be written.
    """
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    try:
        cached, _ = _read_cache(json_file)
    except (OSError, ValueError):
        cached = {}

    tip = fetch_tip_height()
    past: dict[int, int] = {}
    for height in halving_heights(tip):
        # Only heights missing from the cache cost a request
        if height in cached:
            past[height] = cached[height]
        else:
            past[height] = fetch_block_timestamp(height)

    converted: dict[str, Any] = {
        HALVINGS_PAST_KEY: [
            {HEIGHT_KEY: h, BLOCK_TIMESTAMP_KEY: ts} for h, ts in past.items()
        ],
        HALVINGS_NEXT_KEY: estimate_next_halving(tip, now),
    }
    write_validated(converted, json_file, _read_cache)


def ensure_halvings(json_file: PathArg, refresh: bool) -> None:
    """
    Make the halvings cache available, without ever raising.

    A missing or unusable cache is downloaded without asking. A usable cache is
    refreshed only when refresh is True. A failure keeps the existing cache, or
    leaves the chart without halving lines when there is none; it is logged as a
    warning.
    """
    try:
        _read_cache(json_file)
        usable = True
    except (OSError, ValueError):
        usable = False

    if usable and not refresh:
        return
    verb = "Updating" if usable else "Downloading"
    logger.log_info(f"{verb} halvings in: {json_file}")
    try:
        update_halvings(json_file)
    except (ConnectionError, ValueError, OSError) as exc:
        if usable:
            logger.log_warning(f"{exc}. Using the cached halvings.")
        else:
            logger.log_warning(f"{exc}. The chart is drawn without halving lines.")
