#!/usr/bin/env python3
"""
Price models: Golden Ratio bands, power law fit and projection, Rainbow bands, era highs.
"""

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd

from config import (
    CLOSE_COLUMN,
    DATE_COLUMN,
    FIT_DEGREE,
    GENESIS_DATE,
    GOLDEN_RATIO_MULTIPLIERS,
    MIN_FIT_POINTS,
    MOVING_AVERAGE_COLUMN,
    MOVING_AVERAGE_DAYS,
    PROJECTION_FALLBACK_YEARS,
    PROJECTION_YEARS_AFTER_NEXT_HALVING,
    RAINBOW_BANDS,
)

# Rainbow edges are the band boundaries: one more than the bands
RAINBOW_EDGE_COUNT = len(RAINBOW_BANDS) + 1
GENESIS_TIMESTAMP = pd.Timestamp(GENESIS_DATE)
ONE_DAY = pd.Timedelta(days=1)


@dataclass
class PowerLawFit:
    """
    OLS fit of log10(price) = slope * log10(days since genesis) + intercept.

    The residual fields describe log10(price) minus the fitted line over the
    points used by the fit; r_squared is the fit's coefficient of determination.
    """

    slope: float
    intercept: float
    residual_min: float
    residual_max: float
    r_squared: float
    points: int


@dataclass
class EraHigh:
    """The highest close of one halving era."""

    date: dt.datetime
    price: float


def compute_golden_ratio_bands(
    df: pd.DataFrame,
    window: int = MOVING_AVERAGE_DAYS,
    multipliers: list[float] | None = None,
) -> pd.DataFrame:
    """
    Compute the Golden Ratio Multiplier bands from a Date/Close frame.

    Close is resampled to one row per calendar day (gaps forward-filled) so the
    window counts days, not samples. The result has a Date column, an MA column
    (simple moving average, NaN until a full window is available) and one column
    per multiplier, named by the multiplier itself, holding MA * multiplier.
    """
    if multipliers is None:
        multipliers = GOLDEN_RATIO_MULTIPLIERS
    daily = df.set_index(DATE_COLUMN)[CLOSE_COLUMN].resample("D").last().ffill()
    moving_average = daily.rolling(window, min_periods=window).mean()
    bands = pd.DataFrame(
        {DATE_COLUMN: daily.index, MOVING_AVERAGE_COLUMN: moving_average.to_numpy()}
    )
    for multiplier in multipliers:
        bands[multiplier] = bands[MOVING_AVERAGE_COLUMN] * multiplier
    return bands


def floor_to_day(value: dt.datetime) -> pd.Timestamp:
    """Return value as a Timestamp truncated to midnight."""
    return cast(pd.Timestamp, pd.Timestamp(value)).normalize()


def _days_since_genesis(dates: Iterable[dt.datetime]) -> np.ndarray:
    """Return the (fractional) days between the genesis date and each date."""
    index = pd.DatetimeIndex(list(dates))
    return np.asarray((index - GENESIS_TIMESTAMP) / ONE_DAY, dtype=float)


def _log_fair_value(fit: PowerLawFit, days: np.ndarray) -> np.ndarray:
    """Return log10 of the fitted price for positive day counts (NaN otherwise)."""
    positive = days > 0
    log_days = np.log10(np.where(positive, days, 1.0))
    return np.where(positive, fit.slope * log_days + fit.intercept, np.nan)


def fit_power_law(df: pd.DataFrame) -> PowerLawFit:
    """
    Fit log10(price) against log10(days since genesis) by ordinary least squares.

    Rows with a non-positive day count or price are skipped.

    Raises:
        ValueError: fewer than MIN_FIT_POINTS usable rows remain.
    """
    days = _days_since_genesis(df[DATE_COLUMN])
    prices = df[CLOSE_COLUMN].to_numpy(dtype=float)
    usable = (days > 0) & (prices > 0)
    if int(usable.sum()) < MIN_FIT_POINTS:
        raise ValueError(
            f"the power law fit needs at least {MIN_FIT_POINTS} positive points"
        )
    x = np.log10(days[usable])
    y = np.log10(prices[usable])
    slope, intercept = np.polyfit(x, y, FIT_DEGREE)
    residuals = y - (slope * x + intercept)
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if ss_tot == 0:
        r_squared = 1.0 if ss_res == 0 else 0.0
    else:
        r_squared = 1.0 - ss_res / ss_tot
    return PowerLawFit(
        slope=float(slope),
        intercept=float(intercept),
        residual_min=float(residuals.min()),
        residual_max=float(residuals.max()),
        r_squared=r_squared,
        points=int(usable.sum()),
    )


def power_law_price(fit: PowerLawFit, dates: Iterable[dt.datetime]) -> pd.Series:
    """Return the fitted (fair value) price per date; NaN before the genesis date."""
    index = pd.DatetimeIndex(list(dates))
    values = 10 ** _log_fair_value(fit, _days_since_genesis(index))
    return pd.Series(values, index=index)


def projection_dates(
    last_date: dt.datetime,
    next_halving_estimate: dt.datetime | None,
    years_after_halving: int = PROJECTION_YEARS_AFTER_NEXT_HALVING,
) -> pd.DatetimeIndex:
    """
    Return the daily dates to project over, from the day after last_date.

    The projection ends years_after_halving years after the next halving
    estimate, or PROJECTION_FALLBACK_YEARS after last_date when there is none.
    The result is empty when that end is not after last_date.
    """
    last_day = floor_to_day(last_date)
    if next_halving_estimate is None:
        end = last_day + pd.DateOffset(years=PROJECTION_FALLBACK_YEARS)
    else:
        end = floor_to_day(next_halving_estimate) + pd.DateOffset(
            years=years_after_halving
        )
    return pd.date_range(last_day + ONE_DAY, end, freq="D")


def _residual_step(fit: PowerLawFit) -> float:
    """Return the log10 residual width of one Rainbow band."""
    return (fit.residual_max - fit.residual_min) / len(RAINBOW_BANDS)


def rainbow_bands(fit: PowerLawFit, dates: Iterable[dt.datetime]) -> pd.DataFrame:
    """
    Compute the Rainbow band edges on the given dates.

    The result has a Date column and one column per edge, named 0 (bottom) to
    len(RAINBOW_BANDS) (top). Edges are the fair value times 10 raised to
    residual_min + k * step, so they are evenly spaced in log10 residual and
    the outer edges bound the fitted history.
    """
    fair = power_law_price(fit, dates)
    step = _residual_step(fit)
    frame = pd.DataFrame({DATE_COLUMN: fair.index})
    for k in range(RAINBOW_EDGE_COUNT):
        frame[k] = fair.to_numpy() * 10 ** (fit.residual_min + k * step)
    return frame


def era_highs(
    df: pd.DataFrame, halving_dates: list[dt.datetime]
) -> list[EraHigh]:
    """
    Return the highest close of every halving era, oldest first.

    Eras are [start of data, first halving), [halving, next halving) and
    [last halving, end of data], so a halving day belongs to the new era.
    Halving times are cut to their day first, since closes sit at midnight while
    halvings happen at the block time. Eras without data are skipped; no
    halvings gives a single era.
    """
    dates = pd.DatetimeIndex(df[DATE_COLUMN])
    closes = df[CLOSE_COLUMN].to_numpy(dtype=float)
    boundaries = sorted(floor_to_day(d) for d in halving_dates)
    starts: list[pd.Timestamp | None] = [None, *boundaries]
    ends: list[pd.Timestamp | None] = [*boundaries, None]
    highs: list[EraHigh] = []
    for start, end in zip(starts, ends):
        mask = ~np.isnan(closes)
        if start is not None:
            mask &= np.asarray(dates >= start)
        if end is not None:
            mask &= np.asarray(dates < end)
        positions = np.flatnonzero(mask)
        if positions.size == 0:
            continue
        peak = int(positions[np.argmax(closes[positions])])
        highs.append(
            EraHigh(
                date=cast(pd.Timestamp, dates[peak]).to_pydatetime(),
                price=float(closes[peak]),
            )
        )
    return highs
