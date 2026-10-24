#!/usr/bin/env python3
"""
Bitcoin Fibonacci Log Chart - Plot Bitcoin price on a log scale with the Golden Ratio Multiplier bands and halving dates.

Draws Philip Swift's Golden Ratio Multiplier: the 350-day simple moving average of the
daily close and curved bands at Fibonacci-derived multiples of it (1.6, 2, 3, 5, 8, 13, 21).

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
from dataclasses import dataclass
from functools import partial
from typing import Any, NoReturn, cast

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

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

# Golden Ratio Multiplier: window of the moving average and band multipliers
MOVING_AVERAGE_DAYS = 350
GOLDEN_RATIO = 1.6
GOLDEN_RATIO_MULTIPLIERS = [GOLDEN_RATIO, 2, 3, 5, 8, 13, 21]

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
GRID_COLOR = "#E0E0E0"
GRID_LINE_WIDTH = 0.6
HIDDEN_SPINES = ("top", "right")
TEXT_COLOR = "#555555"
TITLE_FONTSIZE = 13
AXIS_LABEL_FONTSIZE = 10
RIGHT_PADDING_FRACTION = 0.09
BAND_LINE_ALPHA = 0.65
BAND_LINE_WIDTH = 1.0
BAND_LINE_STYLE = "--"
GOLDEN_BAND_LINE_STYLE = "-"
BAND_ZORDER = 2
GOLDEN_BAND_COLOR = "#00A86B"
GOLDEN_BAND_LINE_WIDTH = 2.4
GOLDEN_BAND_ALPHA = 1.0
GOLDEN_BAND_ZORDER = 3
PRICE_LINE_WIDTH = 1.5
PRICE_ZORDER = 4
PRICE_COLOR = "#2196F3"
PRICE_FILL_COLOR = to_rgb(PRICE_COLOR)
PRICE_FILL_TOP_ALPHA = 0.35
PRICE_FILL_BOTTOM_ALPHA = 0.02
PRICE_FILL_GRADIENT_STEPS = 256
PRICE_FILL_ZORDER = 1
GRADIENT_EXTENT = (0, 1, 0, 1)
MIN_POINTS_FOR_FILL = 2
MOVING_AVERAGE_COLOR = "#9E9E9E"
MOVING_AVERAGE_LINE_WIDTH = 1.2
MOVING_AVERAGE_ALPHA = 0.9
MOVING_AVERAGE_LINE_STYLE = "--"
# One colour per non-golden multiplier, cool to warm as the multiple grows;
# green is reserved for the golden ratio band
BAND_COLORS = [
    "#9ACD32",
    "#FFB300",
    "#FB8C00",
    "#E64A19",
    "#C62828",
    "#7F0000",
]
if len(BAND_COLORS) != len(GOLDEN_RATIO_MULTIPLIERS) - 1:
    raise ValueError("BAND_COLORS needs one colour per non-golden multiplier")
HALVING_LINE_ALPHA = 0.6
HALVING_LABEL_FONTSIZE = 8

# Chart text
CHART_TITLE = "Bitcoin Price (Log Scale) - Golden Ratio Multiplier and Halving Events"
X_AXIS_LABEL = "Date"
Y_AXIS_LABEL = "Price (log scale)"
PRICE_LABEL = "BTC"
# Minor y ticks get dollar labels only when the view spans less than this ratio
MINOR_LABEL_MAX_RATIO = 10

# Data frame column names
DATE_COLUMN = "Date"
CLOSE_COLUMN = "Close"
MOVING_AVERAGE_COLUMN = "MA"

# End-of-line labels
END_LABEL_FONTSIZE = 9
END_LABEL_OFFSET_POINTS = 6
END_LABEL_GAP_FACTOR = 1.25
POINTS_PER_INCH = 72
GOLDEN_LABEL_WEIGHT = "bold"
NORMAL_LABEL_WEIGHT = "normal"

# Compact dollar formatting
BILLION = 1_000_000_000
MILLION = 1_000_000
THOUSAND = 1_000
SIGNIFICANT_DIGITS = 3
SUB_DOLLAR_DECIMALS = 2
ZERO_DOLLARS = "$0"
ONE_DOLLAR = "$1"
ROUNDED_ONE_DOLLAR = "1.00"


@dataclass
class EndLabel:
    """A line's end-of-line label: where the line ends, its text and its style."""

    x: dt.datetime
    y: float
    text: str
    color: str
    weight: str = NORMAL_LABEL_WEIGHT


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


def halvings_in_range(
    first_date: dt.datetime,
    last_date: dt.datetime,
    halving_dates: list[dt.datetime] | None = None,
) -> list[dt.datetime]:
    """Return the halving dates that fall within [first_date, last_date]."""
    if halving_dates is None:
        halving_dates = HALVING_DATES
    return [d for d in halving_dates if first_date <= d <= last_date]


def _add_gradient_fill(ax: Axes, dates: pd.Series, prices: pd.Series) -> None:
    """
    Fill the area under the price line with a vertical light-blue gradient.

    The gradient is an RGBA image drawn in axes coordinates (the y axis is
    logarithmic, so a data-coordinate image would be distorted) and clipped to
    the polygon between the price line and the bottom of the visible axis. Call
    it after all lines are plotted: the polygon floor is the current lower y
    limit, and the axis limits are restored so the fill never changes autoscaling.
    Series with fewer than MIN_POINTS_FOR_FILL points have no area and are skipped.
    """
    if len(prices) < MIN_POINTS_FOR_FILL:
        return

    x_limits = ax.get_xlim()
    y_floor, y_ceiling = ax.get_ylim()

    # No face or edge of its own: the polygon only serves as the clip path
    polygon = ax.fill_between(
        dates, prices, y_floor, facecolor="none", edgecolor="none", linewidth=0
    )
    # Fixing the limits switches autoscaling off, so imshow cannot rescale the axes
    ax.set_xlim(x_limits)
    ax.set_ylim(y_floor, y_ceiling)
    alphas = np.linspace(
        PRICE_FILL_TOP_ALPHA, PRICE_FILL_BOTTOM_ALPHA, PRICE_FILL_GRADIENT_STEPS
    )
    rgba = np.empty((PRICE_FILL_GRADIENT_STEPS, 1, len(PRICE_FILL_COLOR) + 1))
    rgba[:, :, : len(PRICE_FILL_COLOR)] = PRICE_FILL_COLOR
    rgba[:, 0, -1] = alphas
    image = ax.imshow(
        rgba,
        extent=GRADIENT_EXTENT,
        transform=ax.transAxes,
        aspect="auto",
        origin="upper",
        zorder=PRICE_FILL_ZORDER,
    )
    image.set_clip_path(polygon.get_paths()[0], polygon.get_transform())


def _significant(value: float) -> str:
    """Return value with SIGNIFICANT_DIGITS digits, never in exponent notation."""
    if value >= THOUSAND:
        return f"{value:.0f}"
    return f"{value:.{SIGNIFICANT_DIGITS}g}"


def format_dollars(value: float, _position: int | None = None) -> str:
    """
    Format a price compactly: $0.10, $1, $100, $1K, $83.4K, $1M, $2.5B.

    Values are rounded to SIGNIFICANT_DIGITS before the suffix is chosen, so a
    value just below a threshold is promoted instead of shown as e.g. 1e+03K:
    999.5 gives $1K, 999500 gives $1M and 1e9 gives $1B. A sub-dollar value that
    rounds to 1.00 prints as $1. Zero and negative values (never drawn on a log
    axis) print as $0.
    """
    if value <= 0:
        return ZERO_DOLLARS
    rounded = float(f"{value:.{SIGNIFICANT_DIGITS}g}")
    if rounded >= BILLION:
        return f"${_significant(rounded / BILLION)}B"
    if rounded >= MILLION:
        return f"${_significant(rounded / MILLION)}M"
    if rounded >= THOUSAND:
        return f"${_significant(rounded / THOUSAND)}K"
    if rounded >= 1:
        return f"${_significant(rounded)}"
    text = f"{rounded:.{SUB_DOLLAR_DECIMALS}f}"
    return ONE_DOLLAR if text == ROUNDED_ONE_DOLLAR else f"${text}"


def _spread_label_positions(y_display: list[float], min_gap: float) -> list[float]:
    """
    Push label positions apart until neighbours are at least min_gap apart.

    Works in display coordinates. Labels that collide form a block that is
    re-centred on the mean of its members' original positions, so the block
    moves as little as possible. The result keeps the input order.
    """
    order = sorted(range(len(y_display)), key=lambda i: y_display[i])
    # Each block holds the original indices (sorted) and the position of its lowest label
    blocks: list[tuple[list[int], float]] = []
    for index in order:
        members = [index]
        start = y_display[index]
        while blocks and blocks[-1][1] + len(blocks[-1][0]) * min_gap > start:
            previous, _ = blocks.pop()
            members = previous + members
            start = sum(
                y_display[m] - rank * min_gap for rank, m in enumerate(members)
            ) / len(members)
        blocks.append((members, start))

    spread = [0.0] * len(y_display)
    for members, start in blocks:
        for rank, member in enumerate(members):
            spread[member] = start + rank * min_gap
    return spread


def _add_end_labels(ax: Axes, labels: list[EndLabel]) -> None:
    """
    Write each label just right of its line end, spread apart so none overlap.

    Call it after the layout is final: the spreading happens in display
    coordinates, which depend on the axes size and limits. The block of labels
    is shifted as a whole to stay inside the axes, so gaps are preserved.
    Positions are fixed at build time and may tighten if the window is resized.
    """
    if not labels:
        return
    x_numbers = [float(mdates.date2num(label.x)) for label in labels]
    points = np.column_stack([x_numbers, [label.y for label in labels]])
    display = ax.transData.transform(points)
    min_gap = END_LABEL_FONTSIZE * END_LABEL_GAP_FACTOR * ax.figure.dpi / POINTS_PER_INCH
    spread = _spread_label_positions(display[:, 1].tolist(), min_gap)
    # Keep the whole block (label centres, with half a text height of margin) in the axes
    margin = END_LABEL_FONTSIZE * ax.figure.dpi / POINTS_PER_INCH / 2
    shift = 0.0
    if max(spread) > ax.bbox.y1 - margin:
        shift = ax.bbox.y1 - margin - max(spread)
    if min(spread) + shift < ax.bbox.y0 + margin:
        shift = ax.bbox.y0 + margin - min(spread)
    spread = [position + shift for position in spread]
    moved = ax.transData.inverted().transform(np.column_stack([display[:, 0], spread]))
    for label, y_position in zip(labels, moved[:, 1]):
        ax.annotate(
            label.text,
            xy=(cast(Any, label.x), float(y_position)),
            xytext=(END_LABEL_OFFSET_POINTS, 0),
            textcoords="offset points",
            verticalalignment="center",
            fontsize=END_LABEL_FONTSIZE,
            fontweight=label.weight,
            color=label.color,
            annotation_clip=False,
        )


def _plot_golden_ratio_bands(ax: Axes, bands: pd.DataFrame) -> list[EndLabel]:
    """
    Draw the 350DMA and the multiplier bands and return their end labels.

    The golden ratio band is the only solid, thick line; the others are thin and
    dashed, coloured from BAND_COLORS in order.
    """
    others = [m for m in GOLDEN_RATIO_MULTIPLIERS if m != GOLDEN_RATIO]
    colors = dict(zip(others, BAND_COLORS))
    ma_name = f"{MOVING_AVERAGE_DAYS}DMA"

    ax.plot(
        bands[DATE_COLUMN],
        bands[MOVING_AVERAGE_COLUMN],
        label=ma_name,
        color=MOVING_AVERAGE_COLOR,
        linestyle=MOVING_AVERAGE_LINE_STYLE,
        linewidth=MOVING_AVERAGE_LINE_WIDTH,
        alpha=MOVING_AVERAGE_ALPHA,
        zorder=BAND_ZORDER,
    )
    labels = [_end_label(bands, MOVING_AVERAGE_COLUMN, ma_name, MOVING_AVERAGE_COLOR)]
    for multiplier in GOLDEN_RATIO_MULTIPLIERS:
        is_golden = multiplier == GOLDEN_RATIO
        color = GOLDEN_BAND_COLOR if is_golden else colors[multiplier]
        name = f"x{multiplier:g}"
        ax.plot(
            bands[DATE_COLUMN],
            bands[multiplier],
            label=name,
            color=color,
            linestyle=GOLDEN_BAND_LINE_STYLE if is_golden else BAND_LINE_STYLE,
            linewidth=GOLDEN_BAND_LINE_WIDTH if is_golden else BAND_LINE_WIDTH,
            alpha=GOLDEN_BAND_ALPHA if is_golden else BAND_LINE_ALPHA,
            zorder=GOLDEN_BAND_ZORDER if is_golden else BAND_ZORDER,
        )
        labels.append(
            _end_label(
                bands,
                multiplier,
                name,
                color,
                GOLDEN_LABEL_WEIGHT if is_golden else NORMAL_LABEL_WEIGHT,
            )
        )
    return labels


def _end_label(
    frame: pd.DataFrame,
    column: object,
    name: str,
    color: str,
    weight: str = NORMAL_LABEL_WEIGHT,
) -> EndLabel:
    """Build the label for the last valid value of a frame column."""
    valid = frame.loc[frame[column].notna()]
    last = valid.iloc[-1]
    return EndLabel(
        x=cast(dt.datetime, last[DATE_COLUMN]),
        y=float(last[column]),
        text=f"{name}  {format_dollars(float(last[column]))}",
        color=color,
        weight=weight,
    )


def _minor_label(ax: Axes, value: float, position: int | None = None) -> str:
    """
    Label a minor y tick in dollars when the view spans under a decade, else blank.

    A narrow view can hold no major log tick at all, which would leave the axis
    unlabelled; wide views stay uncluttered.
    """
    low, high = ax.get_ylim()
    if low > 0 and high / low < MINOR_LABEL_MAX_RATIO:
        return format_dollars(value, position)
    return ""


def _style_axes(ax: Axes) -> None:
    """Apply the clean look: no top/right spines, light y grid, dollar y ticks."""
    for side in HIDDEN_SPINES:
        ax.spines[side].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(False)
    ax.grid(True, axis="y", which="major", color=GRID_COLOR, linewidth=GRID_LINE_WIDTH)
    ax.yaxis.set_major_formatter(FuncFormatter(format_dollars))
    ax.yaxis.set_minor_formatter(FuncFormatter(partial(_minor_label, ax)))
    ax.tick_params(which="both", colors=TEXT_COLOR)
    ax.set_title(
        CHART_TITLE,
        fontsize=TITLE_FONTSIZE,
        fontweight="normal",
        color=TEXT_COLOR,
    )
    ax.set_xlabel(X_AXIS_LABEL, fontsize=AXIS_LABEL_FONTSIZE, color=TEXT_COLOR)
    ax.set_ylabel(Y_AXIS_LABEL, fontsize=AXIS_LABEL_FONTSIZE, color=TEXT_COLOR)


def build_chart(df: pd.DataFrame) -> Figure:
    """Draw the log-scale price chart with the Golden Ratio Multiplier and halvings."""
    min_price = cast(float, df[CLOSE_COLUMN].min())
    bands = compute_golden_ratio_bands(df)

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT))
    ax.plot(
        df[DATE_COLUMN],
        df[CLOSE_COLUMN],
        label=PRICE_LABEL,
        color=PRICE_COLOR,
        linewidth=PRICE_LINE_WIDTH,
        zorder=PRICE_ZORDER,
    )
    ax.set_yscale("log")
    _style_axes(ax)

    last_close = cast(float, df[CLOSE_COLUMN].iloc[-1])
    end_labels = [
        EndLabel(
            x=cast(dt.datetime, df[DATE_COLUMN].iloc[-1]),
            y=last_close,
            text=f"{PRICE_LABEL}  {format_dollars(last_close)}",
            color=PRICE_COLOR,
        )
    ]
    # Short histories have no full window: draw the price only
    if bool(bands[MOVING_AVERAGE_COLUMN].notna().any()):
        end_labels += _plot_golden_ratio_bands(ax, bands)

    first_date = cast(dt.datetime, df[DATE_COLUMN].min())
    last_date = cast(dt.datetime, df[DATE_COLUMN].max())
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

    # Room on the right for the end labels
    left, right = ax.get_xlim()
    ax.set_xlim(left, right + (right - left) * RIGHT_PADDING_FRACTION)

    _add_gradient_fill(
        ax, cast(pd.Series, df[DATE_COLUMN]), cast(pd.Series, df[CLOSE_COLUMN])
    )
    fig.tight_layout()
    _add_end_labels(ax, end_labels)
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
    """Load Bitcoin price data, compute the Golden Ratio Multiplier bands, and render the chart."""
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
