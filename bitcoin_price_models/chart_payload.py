#!/usr/bin/env python3
"""
Chart payload: turn the price data and the models into the JSON-serialisable page data.

Schema (times are "YYYY-MM-DD" strings, values are floats, NaN values are dropped):

    {
      "meta": {"initialMode": "golden" | "powerlaw",
               "generatedAt": "<ISO UTC>", "lastDate": "YYYY-MM-DD",
               "priceColor": "#rrggbb"},                price line colour
      "price": [{"time", "value"}, ...],
      "golden": {
        "ma": {"key": "ma", "label": "350DMA", "color", "data": [...]},
        "bands": [{"key": "x1.6", "label": "1.6x Multiplier", "multiplier": 1.6,
                   "color", "golden": true only for 1.6, "data": [...]}, ...]
      },
      "powerlaw": {
        "fairValue": {"key": "fair", "label": "Power Law", "color",
                      "data": [...]},              history plus projection
        "projectionStart": "YYYY-MM-DD",           first projected date
        "fit": {"slope", "intercept", "rSquared"},
        "rainbow": {
          "bands": [{"name", "color"}, ...],       bottom to top
          "edges": [[{"time", "value"}, ...], ...] one array per edge, bottom to top,
                                                   same dates as fairValue
        }
      },
      "eraHighs": [{"time", "price", "label": "$124.8K"}, ...],
      "halvings": {"past": [{"time", "label": "Halving 2024-04-20"}, ...],
                   "next": {"time", "label": "Next halving (est.) 2028-04-11"} | null}
    }

Dates are cut to the day before deduplication, so each price time is unique.
A next halving estimate on or before the last price date is stale: halvings.next
is null and the projection uses its fallback horizon.
When the projection is empty, projectionStart is the day after meta.lastDate.
"""

import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import numpy as np
import pandas as pd

from config import (
    BAND_COLORS,
    BAND_KEY_PREFIX,
    BAND_LABEL_SUFFIX,
    BILLION,
    CLOSE_COLUMN,
    DATE_COLUMN,
    DATE_FORMAT,
    FAIR_VALUE_COLOR,
    FAIR_VALUE_KEY,
    FAIR_VALUE_LABEL,
    GOLDEN_BAND_COLOR,
    GOLDEN_RATIO,
    HALVING_LABEL_PREFIX,
    LARGE_DECIMALS,
    MILLION,
    MODES,
    MOVING_AVERAGE_COLOR,
    MOVING_AVERAGE_COLUMN,
    MOVING_AVERAGE_KEY,
    MOVING_AVERAGE_LABEL,
    NEXT_HALVING_LABEL_PREFIX,
    PRICE_COLOR,
    RAINBOW_BANDS,
    SMALL_DECIMALS,
    TEN,
    THOUSAND,
    GOLDEN_RATIO_MULTIPLIERS,
)
from halvings import HalvingInfo
from models import (
    RAINBOW_EDGE_COUNT,
    compute_golden_ratio_bands,
    era_highs,
    fit_power_law,
    floor_to_day,
    power_law_price,
    projection_dates,
    rainbow_bands,
)

# Values are rounded to this many significant digits to keep the page small
SIGNIFICANT_DIGITS = 6
ONE_DAY = dt.timedelta(days=1)


def format_compact_dollars(value: float) -> str:
    """
    Format a price compactly: $33.80, $1.14K, $19.3K, $124.8K, $1.2M.

    Below 1000 two decimals are shown; thousands show two decimals under 10K and
    one above; millions and billions show one. A value that rounds up to the next
    unit is promoted, so 999999 gives $1.0M.
    """
    if round(value, SMALL_DECIMALS) < THOUSAND:
        return f"${value:.{SMALL_DECIMALS}f}"
    # A price that only rounds up to 1000 belongs to the thousands
    value = max(value, THOUSAND)
    for unit, suffix in ((BILLION, "B"), (MILLION, "M"), (THOUSAND, "K")):
        if value < unit:
            continue
        scaled = value / unit
        decimals = SMALL_DECIMALS if unit == THOUSAND and scaled < TEN else LARGE_DECIMALS
        text = f"{scaled:.{decimals}f}"
        if float(text) >= THOUSAND and unit != BILLION:
            return format_compact_dollars(unit * THOUSAND)
        return f"${text}{suffix}"
    return f"${value:.{SMALL_DECIMALS}f}"


def _day_string(value: Any) -> str:
    """Return a datetime-like value as a YYYY-MM-DD string."""
    return value.strftime(DATE_FORMAT)


def _round(value: float) -> float:
    """Round value to SIGNIFICANT_DIGITS significant digits."""
    return float(f"{value:.{SIGNIFICANT_DIGITS}g}")


def _points(dates: Iterable[Any], values: Iterable[float]) -> list[dict[str, Any]]:
    """Pair dates with values as {time, value} dicts, skipping NaN and infinite values."""
    return [
        {"time": _day_string(date), "value": _round(float(value))}
        for date, value in zip(dates, values)
        if np.isfinite(value)
    ]


def _series(key: str, label: str, color: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    """Return one named line series."""
    return {"key": key, "label": label, "color": color, "data": points}


def _golden_payload(df: pd.DataFrame) -> dict[str, Any]:
    """Return the Golden Ratio section: the moving average and its multiplier bands."""
    frame = compute_golden_ratio_bands(df)
    dates = frame[DATE_COLUMN]
    other_colors = iter(BAND_COLORS)
    bands = []
    for multiplier in GOLDEN_RATIO_MULTIPLIERS:
        is_golden = multiplier == GOLDEN_RATIO
        color = GOLDEN_BAND_COLOR if is_golden else next(other_colors)
        band = _series(
            f"{BAND_KEY_PREFIX}{multiplier:g}",
            f"{multiplier:g}{BAND_LABEL_SUFFIX}",
            color,
            _points(dates, frame[multiplier]),
        )
        band["multiplier"] = multiplier
        band["golden"] = is_golden
        bands.append(band)
    moving_average = _series(
        MOVING_AVERAGE_KEY,
        MOVING_AVERAGE_LABEL,
        MOVING_AVERAGE_COLOR,
        _points(dates, frame[MOVING_AVERAGE_COLUMN]),
    )
    return {"ma": moving_average, "bands": bands}


def _power_law_payload(
    df: pd.DataFrame, last_date: pd.Timestamp, halvings: HalvingInfo
) -> dict[str, Any]:
    """Return the Power Law section: fair value, projection start, fit and Rainbow edges."""
    fit = fit_power_law(df)
    future = projection_dates(last_date, halvings.next_estimate)
    history = pd.DatetimeIndex(df[DATE_COLUMN]).unique().sort_values()
    dates = history.append(future)
    fair = power_law_price(fit, dates)
    edges = rainbow_bands(fit, dates)
    start = future[0] if len(future) else last_date + ONE_DAY
    return {
        "fairValue": _series(
            FAIR_VALUE_KEY,
            FAIR_VALUE_LABEL,
            FAIR_VALUE_COLOR,
            _points(dates, fair.to_numpy()),
        ),
        "projectionStart": _day_string(start),
        "fit": {
            "slope": fit.slope,
            "intercept": fit.intercept,
            "rSquared": fit.r_squared,
        },
        "rainbow": {
            "bands": [{"name": name, "color": color} for name, color in RAINBOW_BANDS],
            "edges": [
                _points(dates, edges[k].to_numpy()) for k in range(RAINBOW_EDGE_COUNT)
            ],
        },
    }


def _halvings_payload(halvings: HalvingInfo) -> dict[str, Any]:
    """Return the halving markers: past dates and the estimated next one (or null)."""
    nxt = halvings.next_estimate
    return {
        "past": [
            {"time": _day_string(d), "label": f"{HALVING_LABEL_PREFIX} {_day_string(d)}"}
            for d in sorted(halvings.past)
        ],
        "next": None
        if nxt is None
        else {
            "time": _day_string(nxt),
            "label": f"{NEXT_HALVING_LABEL_PREFIX} {_day_string(nxt)}",
        },
    }


def build_payload(df: pd.DataFrame, halvings: HalvingInfo, mode: str) -> dict[str, Any]:
    """
    Build the page data (see the module docstring) from a Date/Close frame.

    Raises:
        ValueError: mode is unknown, the frame has no usable price, or the power law
            fit has too few points.
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}, expected one of {MODES}")
    valid = df.dropna(subset=[DATE_COLUMN, CLOSE_COLUMN])
    # Cut to the day before deduping so intraday points cannot repeat a time
    clean = (
        valid.assign(**{DATE_COLUMN: pd.to_datetime(valid[DATE_COLUMN]).dt.normalize()})
        .drop_duplicates(subset=DATE_COLUMN, keep="last")
        .sort_values(DATE_COLUMN)
        .reset_index(drop=True)
    )
    if clean.empty:
        raise ValueError("there is no price data to chart")
    last_date = cast(pd.Timestamp, pd.Timestamp(clean[DATE_COLUMN].iloc[-1]))
    nxt = halvings.next_estimate
    if nxt is not None and floor_to_day(nxt) <= last_date:
        # The estimate is already behind the data, so it is stale
        halvings = HalvingInfo(past=halvings.past, next_estimate=None)
    return {
        "meta": {
            "initialMode": mode,
            "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "lastDate": _day_string(last_date),
            "priceColor": PRICE_COLOR,
        },
        "price": _points(clean[DATE_COLUMN], clean[CLOSE_COLUMN]),
        "golden": _golden_payload(clean),
        "powerlaw": _power_law_payload(clean, last_date, halvings),
        "eraHighs": [
            {
                "time": _day_string(high.date),
                "price": _round(high.price),
                "label": format_compact_dollars(high.price),
            }
            for high in era_highs(clean, halvings.past)
        ],
        "halvings": _halvings_payload(halvings),
    }
