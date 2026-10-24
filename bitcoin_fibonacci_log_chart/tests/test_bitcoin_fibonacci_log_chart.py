"""Tests for bitcoin_fibonacci_log_chart: price-file parsing and validation, Golden Ratio
Multiplier band math, halving filtering, chart construction (headless Agg backend), and main().
The real market-price.json is never read: every test builds its own data in tmp_path.
"""

from __future__ import annotations

import datetime as dt
import http.client
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import cast

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.text import Annotation

import bitcoin_fibonacci_log_chart as bfc

MS_PER_DAY = 86_400_000
EPOCH_2012_12_01_MS = int(dt.datetime(2012, 12, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def write_json(path: Path, payload) -> Path:
    """Write payload as JSON to path."""
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def series(*prices: float, start_ms: int = 0) -> dict:
    """Build a blockchain.com style payload with one point per day."""
    return {
        "market-price": [
            {"x": start_ms + i * MS_PER_DAY, "y": p} for i, p in enumerate(prices)
        ]
    }


def end_labels(ax: Axes) -> list[str]:
    """Return the texts of the end-of-line labels, in drawing order."""
    return [t.get_text() for t in ax.texts if isinstance(t, Annotation)]


def label_display_ys(ax: Axes) -> list[float]:
    """Return the sorted display y of every end label, using each label's real x."""
    ys = []
    for t in ax.texts:
        if isinstance(t, Annotation):
            point = np.array([[float(mdates.date2num(t.xy[0])), float(t.xy[1])]])
            ys.append(float(ax.transData.transform(point)[0, 1]))
    return sorted(ys)


def halving_texts(ax: Axes) -> list[str]:
    """Return the texts of the halving date markers."""
    return [t.get_text() for t in ax.texts if not isinstance(t, Annotation)]


def line_by_label(ax: Axes, label: str) -> Line2D:
    """Return the plotted line carrying the given label."""
    return next(line for line in ax.lines if line.get_label() == label)


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def test_backend_is_headless():
    assert matplotlib.get_backend().lower() == "agg"


class TestLoadPriceData:
    def test_basic_parse(self, tmp_path):
        path = write_json(tmp_path / "p.json", series(10.0, 20.0, 30.0))
        df = bfc.load_price_data(path)
        assert list(df.columns) == ["Date", "Close"]
        assert df["Close"].tolist() == [10.0, 20.0, 30.0]
        assert df["Date"].iloc[0] == pd.Timestamp("1970-01-01")
        assert df["Date"].iloc[1] == pd.Timestamp("1970-01-02")

    def test_zero_and_negative_prices_dropped(self, tmp_path):
        path = write_json(tmp_path / "p.json", series(0, 0, 5.0, -1, 7.0))
        assert bfc.load_price_data(path)["Close"].tolist() == [5.0, 7.0]

    def test_rows_sorted_by_date(self, tmp_path):
        payload = {
            "market-price": [
                {"x": 2 * MS_PER_DAY, "y": 3.0},
                {"x": 0, "y": 1.0},
                {"x": MS_PER_DAY, "y": 2.0},
            ]
        }
        df = bfc.load_price_data(write_json(tmp_path / "p.json", payload))
        assert df["Close"].tolist() == [1.0, 2.0, 3.0]
        assert df["Date"].is_monotonic_increasing

    def test_null_prices_are_dropped(self, tmp_path):
        payload = {"market-price": [{"x": 0, "y": None}, {"x": MS_PER_DAY, "y": 4.0}]}
        df = bfc.load_price_data(write_json(tmp_path / "p.json", payload))
        assert df["Close"].tolist() == [4.0]

    def test_all_zero_prices_rejected(self, tmp_path):
        path = write_json(tmp_path / "p.json", series(0, 0, 0))
        with pytest.raises(ValueError, match="no positive prices"):
            bfc.load_price_data(path)

    def test_empty_series_rejected(self, tmp_path):
        path = write_json(tmp_path / "p.json", {"market-price": []})
        with pytest.raises(ValueError):
            bfc.load_price_data(path)

    def test_missing_series_key_rejected(self, tmp_path):
        path = write_json(tmp_path / "p.json", {"other": []})
        with pytest.raises(ValueError, match="market-price"):
            bfc.load_price_data(path)

    def test_top_level_list_rejected(self, tmp_path):
        path = write_json(tmp_path / "p.json", [1, 2, 3])
        with pytest.raises(ValueError):
            bfc.load_price_data(path)

    def test_missing_fields_rejected(self, tmp_path):
        path = write_json(tmp_path / "p.json", {"market-price": [{"a": 1}]})
        with pytest.raises(ValueError, match="fields"):
            bfc.load_price_data(path)

    def test_invalid_json_rejected(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            bfc.load_price_data(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            bfc.load_price_data(tmp_path / "missing.json")


class TestGoldenRatioBands:
    WINDOW = 4

    def _frame(self, prices, start="2020-01-01"):
        dates = pd.date_range(start, periods=len(prices), freq="D")
        return pd.DataFrame({"Date": dates, "Close": prices})

    def test_warm_up_is_nan_then_mean(self):
        bands = bfc.compute_golden_ratio_bands(
            self._frame([1.0, 2.0, 3.0, 4.0, 5.0]), window=self.WINDOW, multipliers=[2]
        )
        assert bands["MA"].iloc[: self.WINDOW - 1].isna().all()
        assert bands["MA"].iloc[self.WINDOW - 1] == pytest.approx(2.5)
        assert bands["MA"].iloc[self.WINDOW] == pytest.approx(3.5)

    def test_constant_price_gives_scaled_bands(self):
        bands = bfc.compute_golden_ratio_bands(
            self._frame([10.0] * 6), window=self.WINDOW, multipliers=[1.6, 5]
        )
        last = bands.iloc[-1]
        assert last["MA"] == pytest.approx(10.0)
        assert last[1.6] == pytest.approx(16.0)
        assert last[5] == pytest.approx(50.0)

    def test_gaps_are_resampled_to_daily(self):
        frame = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2020-01-01", "2020-01-04", "2020-01-05"]),
                "Close": [1.0, 4.0, 5.0],
            }
        )
        bands = bfc.compute_golden_ratio_bands(frame, window=self.WINDOW, multipliers=[])
        assert len(bands) == 5
        assert bands["Date"].tolist() == list(pd.date_range("2020-01-01", periods=5))
        # Days 2 and 3 carry the last known price forward: mean(1, 1, 1, 4)
        assert bands["MA"].iloc[3] == pytest.approx(1.75)
        assert bands["MA"].iloc[:3].isna().all()

    def test_default_multipliers(self):
        assert bfc.GOLDEN_RATIO_MULTIPLIERS == [1.6, 2, 3, 5, 8, 13, 21]
        assert bfc.MOVING_AVERAGE_DAYS == 350
        bands = bfc.compute_golden_ratio_bands(self._frame([1.0, 2.0]), window=2)
        assert list(bands.columns) == ["Date", "MA", *bfc.GOLDEN_RATIO_MULTIPLIERS]

    def test_short_data_is_all_nan(self):
        bands = bfc.compute_golden_ratio_bands(self._frame([1.0, 2.0, 3.0]), window=self.WINDOW)
        assert bool(bands["MA"].isna().all())
        assert bool(bands[21].isna().all())


class TestHalvings:
    def test_only_dates_inside_range(self):
        result = bfc.halvings_in_range(dt.datetime(2015, 1, 1), dt.datetime(2021, 1, 1))
        assert result == [dt.datetime(2016, 7, 9), dt.datetime(2020, 5, 11)]

    def test_bounds_are_inclusive(self):
        result = bfc.halvings_in_range(dt.datetime(2012, 11, 28), dt.datetime(2012, 11, 28))
        assert result == [dt.datetime(2012, 11, 28)]

    def test_empty_when_range_has_no_halving(self):
        assert bfc.halvings_in_range(dt.datetime(2013, 1, 1), dt.datetime(2014, 1, 1)) == []

    def test_works_with_pandas_timestamps(self):
        first = cast(dt.datetime, pd.Timestamp("2010-01-01"))
        last = cast(dt.datetime, pd.Timestamp("2030-01-01"))
        result = bfc.halvings_in_range(first, last)
        assert result == bfc.HALVING_DATES

    def test_halving_dates_are_chronological(self):
        assert bfc.HALVING_DATES == sorted(bfc.HALVING_DATES)


class TestBuildChart:
    def _df(self, tmp_path, payload):
        return bfc.load_price_data(write_json(tmp_path / "p.json", payload))

    def _long_axes(self, tmp_path):
        days = bfc.MOVING_AVERAGE_DAYS + 10
        df = self._df(tmp_path, series(*[10.0 + i for i in range(days)]))
        return bfc.build_chart(df).axes[0]

    def test_log_scale_and_no_legend(self, tmp_path):
        ax = self._long_axes(tmp_path)
        assert ax.get_yscale() == "log"
        assert ax.get_legend() is None

    def test_one_end_label_per_line_with_long_data(self, tmp_path):
        ax = self._long_axes(tmp_path)
        labels = end_labels(ax)
        assert len(labels) == 2 + len(bfc.GOLDEN_RATIO_MULTIPLIERS)
        assert labels[0].startswith("BTC  $")
        assert any(t.startswith(f"{bfc.MOVING_AVERAGE_DAYS}DMA  $") for t in labels)
        assert any(t.startswith("x1.6  $") for t in labels)
        assert any(t.startswith("x21  $") for t in labels)
        assert halving_texts(ax) == []

    def test_short_series_draws_price_and_btc_label_only(self, tmp_path):
        df = self._df(tmp_path, series(10.0, 100.0, 1000.0))
        ax = bfc.build_chart(df).axes[0]
        assert len(ax.lines) == 1
        assert end_labels(ax) == ["BTC  $1K"]

    def test_golden_band_is_solid_and_thickest(self, tmp_path):
        ax = self._long_axes(tmp_path)
        golden = line_by_label(ax, "x1.6")
        assert golden.get_linestyle() == "-"
        assert golden.get_color() == bfc.GOLDEN_BAND_COLOR
        others = [
            line_by_label(ax, f"x{m:g}")
            for m in bfc.GOLDEN_RATIO_MULTIPLIERS
            if m != bfc.GOLDEN_RATIO
        ]
        for line in others:
            assert line.get_linestyle() == "--"
            assert line.get_linewidth() < golden.get_linewidth()
            assert line.get_zorder() < golden.get_zorder()
        price = line_by_label(ax, "BTC")
        assert golden.get_zorder() < price.get_zorder()

    def test_band_colors_match_non_golden_multipliers(self):
        others = [m for m in bfc.GOLDEN_RATIO_MULTIPLIERS if m != bfc.GOLDEN_RATIO]
        assert len(bfc.BAND_COLORS) == len(others)
        assert bfc.GOLDEN_BAND_COLOR not in bfc.BAND_COLORS
        assert len(set(bfc.BAND_COLORS)) == len(bfc.BAND_COLORS)

    def test_moving_average_is_grey_dashed(self, tmp_path):
        ax = self._long_axes(tmp_path)
        line = line_by_label(ax, f"{bfc.MOVING_AVERAGE_DAYS}DMA")
        assert line.get_color() == bfc.MOVING_AVERAGE_COLOR
        assert line.get_linestyle() == "--"

    def test_axes_are_clean(self, tmp_path):
        ax = self._long_axes(tmp_path)
        assert not ax.spines["top"].get_visible()
        assert not ax.spines["right"].get_visible()
        assert not ax.xaxis.get_gridlines()[0].get_visible()
        assert ax.yaxis.get_gridlines()[0].get_visible()
        assert ax.yaxis.get_major_formatter()(1000.0, 0) == "$1K"

    def test_end_labels_do_not_overlap(self, tmp_path):
        days = bfc.MOVING_AVERAGE_DAYS + 10
        fig = bfc.build_chart(self._df(tmp_path, series(*[10.0 + i for i in range(days)])))
        ax = fig.axes[0]
        ys = label_display_ys(ax)
        min_gap = bfc.END_LABEL_FONTSIZE * bfc.END_LABEL_GAP_FACTOR * fig.dpi / bfc.POINTS_PER_INCH
        assert all(b - a >= min_gap - 1e-6 for a, b in zip(ys, ys[1:]))

    def test_halving_markers_only_when_in_data_range(self, tmp_path):
        inside = self._df(tmp_path, series(1.0, 2.0, 3.0, start_ms=EPOCH_2012_12_01_MS - 5 * MS_PER_DAY))
        fig = bfc.build_chart(inside)
        assert halving_texts(fig.axes[0]) == ["2012-11-28"]

        outside = self._df(tmp_path, series(1.0, 2.0, start_ms=EPOCH_2012_12_01_MS))
        assert halving_texts(bfc.build_chart(outside).axes[0]) == []

    def test_single_point_does_not_crash(self, tmp_path):
        df = self._df(tmp_path, series(42.0))
        ax = bfc.build_chart(df).axes[0]
        assert len(ax.images) == 0
        assert len(ax.lines) == 1
        assert end_labels(ax) == ["BTC  $42"]

    def test_narrow_range_still_shows_dollar_labels(self, tmp_path):
        prices = [45_000.0 + 500.0 * i for i in range(100)]
        fig = bfc.build_chart(self._df(tmp_path, series(*prices)))
        ax = fig.axes[0]
        fig.canvas.draw()
        texts = [
            t.get_text()
            for t in ax.get_yticklabels() + ax.get_yticklabels(minor=True)
            if t.get_text()
        ]
        assert len(texts) >= 2
        assert all(text.startswith("$") for text in texts)

    def test_wide_range_has_no_minor_labels(self, tmp_path):
        ax = self._long_axes(tmp_path)
        ax.figure.canvas.draw()
        assert [t for t in ax.get_yticklabels(minor=True) if t.get_text()] == []

    def test_end_labels_stay_inside_axes_near_top_edge(self):
        fig, ax = plt.subplots()
        ax.plot(np.array(["2020-01-01", "2020-01-02"], dtype="datetime64[D]"), [1, 1])
        ax.set_yscale("log")
        ax.set_ylim(1, 1000)
        fig.canvas.draw()
        top = [990.0, 995.0, 998.0, 999.0, 1000.0]
        x = dt.datetime(2020, 1, 2)
        bfc._add_end_labels(ax, [bfc.EndLabel(x, y, f"L{y}", "black") for y in top])
        ys = label_display_ys(ax)
        min_gap = bfc.END_LABEL_FONTSIZE * bfc.END_LABEL_GAP_FACTOR * fig.dpi / bfc.POINTS_PER_INCH
        assert ys[-1] <= ax.bbox.y1 + 1e-6
        assert ys[0] >= ax.bbox.y0
        assert all(b - a >= min_gap - 1e-6 for a, b in zip(ys, ys[1:]))

    def test_gradient_fill_is_one_clipped_image(self, tmp_path):
        df = self._df(tmp_path, series(10.0, 100.0, 1000.0))
        ax = bfc.build_chart(df).axes[0]
        assert len(ax.images) == 1
        image = ax.images[0]
        assert image.get_clip_path() is not None
        assert image.get_zorder() < ax.lines[0].get_zorder()

    def test_gradient_alpha_fades_downward(self, tmp_path):
        df = self._df(tmp_path, series(10.0, 100.0, 1000.0))
        image = bfc.build_chart(df).axes[0].images[0]
        alphas = np.asarray(image.get_array())[:, 0, -1]
        assert alphas[0] == pytest.approx(bfc.PRICE_FILL_TOP_ALPHA)
        assert alphas[-1] == pytest.approx(bfc.PRICE_FILL_BOTTOM_ALPHA)
        assert bool((alphas[:-1] >= alphas[1:]).all())

    def test_gradient_fill_keeps_limits_and_btc_label(self, tmp_path):
        df = self._df(tmp_path, series(10.0, 100.0, 1000.0))
        ax = bfc.build_chart(df).axes[0]
        floor, ceiling = ax.get_ylim()
        assert floor <= 10.0 and ceiling >= 1000.0
        assert end_labels(ax) == ["BTC  $1K"]

    def test_gradient_fill_with_full_band_set_keeps_labels(self, tmp_path):
        ax = self._long_axes(tmp_path)
        assert len(ax.images) == 1
        assert len(end_labels(ax)) == 2 + len(bfc.GOLDEN_RATIO_MULTIPLIERS)


class TestFormatDollars:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0.1, "$0.10"),
            (1, "$1"),
            (100, "$100"),
            (1000, "$1K"),
            (83_400, "$83.4K"),
            (125_000, "$125K"),
            (1e6, "$1M"),
            (999_999, "$1M"),
            (999.5, "$1K"),
            (999.4, "$999"),
            (999_500, "$1M"),
            (999_499, "$999K"),
            (999_500_000, "$1B"),
            (1e9, "$1B"),
            (2.5e9, "$2.5B"),
            (1e12, "$1000B"),
            (0.9999, "$1"),
            (0.999, "$1"),
            (0.5, "$0.50"),
            (0, "$0"),
            (-5, "$0"),
        ],
    )
    def test_compact_values(self, value, expected):
        assert bfc.format_dollars(value) == expected

    def test_tick_position_argument_is_accepted(self):
        assert bfc.format_dollars(10_000, 3) == "$10K"


class TestSpreadLabelPositions:
    GAP = 10.0

    def test_separated_positions_are_unchanged(self):
        positions = [0.0, 25.0, 100.0]
        assert bfc._spread_label_positions(positions, self.GAP) == positions

    def test_overlapping_positions_end_up_min_gap_apart(self):
        result = bfc._spread_label_positions([50.0, 52.0, 51.0, 80.0], self.GAP)
        ordered = sorted(result)
        assert all(b - a >= self.GAP - 1e-9 for a, b in zip(ordered, ordered[1:]))

    def test_output_order_matches_input_order(self):
        positions = [52.0, 50.0, 80.0, 51.0]
        result = bfc._spread_label_positions(positions, self.GAP)
        assert np.argsort(result).tolist() == np.argsort(positions).tolist()

    def test_cluster_stays_centred_on_original_positions(self):
        result = bfc._spread_label_positions([50.0, 50.0], self.GAP)
        assert sorted(result) == pytest.approx([45.0, 55.0])

    def test_chain_merge_pulls_in_the_next_neighbour(self):
        # [0, 9] collide, the merged block then reaches 18 and absorbs it too
        result = bfc._spread_label_positions([0.0, 9.0, 18.0], self.GAP)
        assert result == pytest.approx([-1.0, 9.0, 19.0])

    def test_ties_are_split_in_input_order(self):
        result = bfc._spread_label_positions([50.0, 50.0, 50.0], self.GAP)
        assert result == pytest.approx([40.0, 50.0, 60.0])

    def test_empty_input(self):
        assert bfc._spread_label_positions([], self.GAP) == []


class FakeResponse:
    """Minimal urlopen response usable as a context manager."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


class TruncatedResponse(FakeResponse):
    """Response whose body ends before the announced length."""

    def read(self, size: int = -1) -> bytes:
        raise http.client.IncompleteRead(b"")


def api_payload(*prices: float) -> dict:
    """Build a blockchain.com API response with timestamps in seconds."""
    return {
        "status": "ok",
        "unit": "USD",
        "values": [{"x": 86_400 * (i + 1), "y": p} for i, p in enumerate(prices)],
    }


def fake_urlopen(payload) -> object:
    """Return a urlopen replacement serving payload as JSON."""
    body = json.dumps(payload).encode("utf-8")
    return lambda *a, **k: FakeResponse(body)


def failing_urlopen(*_a, **_k):
    """urlopen replacement simulating a network failure."""
    raise urllib.error.URLError("offline")


def set_mtime(path: Path, when: dt.datetime) -> None:
    """Set the modification time of path to when (local time)."""
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))


class TestDownloadPriceData:
    def test_converts_seconds_to_ms_and_loads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", fake_urlopen(api_payload(5.0, 7.0))
        )
        target = tmp_path / "market-price.json"
        bfc.download_price_data(str(target))
        saved = json.loads(target.read_text(encoding="utf-8"))
        assert saved == {"market-price": [{"x": 86_400_000, "y": 5.0},
                                          {"x": 172_800_000, "y": 7.0}]}
        assert bfc.load_price_data(target)["Close"].tolist() == [5.0, 7.0]
        assert list(tmp_path.iterdir()) == [target]

    @pytest.mark.parametrize(
        "payload",
        [
            {"status": "error", "values": [{"x": 1, "y": 1.0}]},
            {"status": "ok"},
            {"status": "ok", "values": []},
            {"status": "ok", "values": [{"x": 1}]},
            [1, 2],
        ],
    )
    def test_bad_response_rejected_and_file_untouched(
        self, tmp_path, monkeypatch, payload
    ):
        target = write_json(tmp_path / "market-price.json", series(1.0))
        before = target.read_text(encoding="utf-8")
        monkeypatch.setattr(bfc.urllib.request, "urlopen", fake_urlopen(payload))
        with pytest.raises(ValueError):
            bfc.download_price_data(str(target))
        assert target.read_text(encoding="utf-8") == before
        assert list(tmp_path.iterdir()) == [target]

    def test_non_json_response_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", lambda *a, **k: FakeResponse(b"<html>")
        )
        with pytest.raises(ValueError, match="not valid JSON"):
            bfc.download_price_data(str(tmp_path / "market-price.json"))

    def test_network_error_keeps_existing_file(self, tmp_path, monkeypatch):
        target = write_json(tmp_path / "market-price.json", series(1.0))
        before = target.read_text(encoding="utf-8")
        monkeypatch.setattr(bfc.urllib.request, "urlopen", failing_urlopen)
        with pytest.raises(ConnectionError):
            bfc.download_price_data(str(target))
        assert target.read_text(encoding="utf-8") == before
        assert list(tmp_path.iterdir()) == [target]

    @pytest.mark.parametrize(
        "x_value",
        [float("inf"), float("nan"), "5", None, True, [1]],
        ids=["inf", "nan", "string", "null", "bool", "list"],
    )
    def test_malformed_timestamp_rejected(self, tmp_path, monkeypatch, x_value):
        payload = {"status": "ok", "values": [{"x": x_value, "y": 1.0}]}
        monkeypatch.setattr(bfc.urllib.request, "urlopen", fake_urlopen(payload))
        target = tmp_path / "market-price.json"
        with pytest.raises(ValueError, match="malformed price entries"):
            bfc.download_price_data(str(target))
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize("price", [0, None, "abc"], ids=["zero", "null", "text"])
    def test_unusable_prices_keep_existing_file(self, tmp_path, monkeypatch, price):
        target = write_json(tmp_path / "market-price.json", series(1.0))
        before = target.read_text(encoding="utf-8")
        payload = {"status": "ok", "values": [{"x": 86_400, "y": price}]}
        monkeypatch.setattr(bfc.urllib.request, "urlopen", fake_urlopen(payload))
        with pytest.raises(ValueError, match="unusable"):
            bfc.download_price_data(str(target))
        assert target.read_text(encoding="utf-8") == before
        assert list(tmp_path.iterdir()) == [target]

    def test_incomplete_read_becomes_connection_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", lambda *a, **k: TruncatedResponse(b"")
        )
        with pytest.raises(ConnectionError):
            bfc.download_price_data(str(tmp_path / "market-price.json"))

    def test_oversized_response_rejected(self, tmp_path, monkeypatch):
        body = json.dumps(api_payload(1.0, 2.0, 3.0)).encode("utf-8")
        monkeypatch.setattr(bfc, "MAX_DOWNLOAD_BYTES", len(body) - 1)
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", lambda *a, **k: FakeResponse(body)
        )
        with pytest.raises(ValueError, match="exceeds"):
            bfc.download_price_data(str(tmp_path / "market-price.json"))
        assert list(tmp_path.iterdir()) == []

    def test_response_at_size_cap_accepted(self, tmp_path, monkeypatch):
        body = json.dumps(api_payload(1.0, 2.0)).encode("utf-8")
        monkeypatch.setattr(bfc, "MAX_DOWNLOAD_BYTES", len(body))
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", lambda *a, **k: FakeResponse(body)
        )
        target = tmp_path / "market-price.json"
        bfc.download_price_data(str(target))
        assert target.exists()

    def test_fdopen_failure_closes_descriptor_and_cleans_up(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", fake_urlopen(api_payload(2.0))
        )
        closed: list[int] = []
        real_close = os.close

        def boom(*_a, **_k):
            raise MemoryError("no handle")

        def tracking_close(fd):
            closed.append(fd)
            real_close(fd)

        monkeypatch.setattr(bfc.os, "fdopen", boom)
        monkeypatch.setattr(bfc.os, "close", tracking_close)
        with pytest.raises(MemoryError):
            bfc.download_price_data(str(tmp_path / "market-price.json"))
        assert len(closed) == 1
        assert list(tmp_path.iterdir()) == []

    def test_cleanup_failure_does_not_mask_original_error(
        self, tmp_path, monkeypatch
    ):
        target = tmp_path / "market-price.json"
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", fake_urlopen(api_payload(2.0))
        )

        def locked(*_a, **_k):
            raise PermissionError("locked")

        monkeypatch.setattr(bfc.os, "replace", locked)
        real_remove = os.remove

        def remove_fails(path):
            real_remove(path)
            raise PermissionError("remove failed")

        monkeypatch.setattr(bfc.os, "remove", remove_fails)
        with pytest.raises(PermissionError, match="locked"):
            bfc.download_price_data(str(target))

    def test_write_failure_cleans_temp_file(self, tmp_path, monkeypatch):
        target = write_json(tmp_path / "market-price.json", series(1.0))
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", fake_urlopen(api_payload(2.0))
        )

        def boom(*_a, **_k):
            raise PermissionError("locked")

        monkeypatch.setattr(bfc.os, "replace", boom)
        with pytest.raises(PermissionError):
            bfc.download_price_data(str(target))
        assert list(tmp_path.iterdir()) == [target]


class TestIsDataCurrent:
    def test_missing_file(self, tmp_path):
        assert bfc.is_data_current(str(tmp_path / "nope.json")) is False

    def test_modified_today(self, tmp_path):
        path = write_json(tmp_path / "p.json", series(1.0))
        assert bfc.is_data_current(str(path)) is True

    def test_modified_earlier(self, tmp_path):
        path = write_json(tmp_path / "p.json", series(1.0))
        set_mtime(path, dt.datetime.now() - dt.timedelta(days=2))
        assert bfc.is_data_current(str(path)) is False


class TestAskYesNo:
    @pytest.mark.parametrize(
        ("answer", "expected"),
        [("y", True), ("YES", True), (" y ", True), ("n", False), ("", False)],
    )
    def test_answers(self, monkeypatch, answer, expected):
        monkeypatch.setattr("builtins.input", lambda *_a: answer)
        assert bfc.ask_yes_no("?") is expected

    @pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
    def test_eof_and_interrupt_count_as_no(self, monkeypatch, error):
        def raise_error(*_a):
            raise error

        monkeypatch.setattr("builtins.input", raise_error)
        assert bfc.ask_yes_no("?") is False


class TestMain:
    @pytest.fixture
    def shown(self, monkeypatch):
        calls: list[bool] = []
        monkeypatch.setattr(bfc.plt, "show", lambda *a, **k: calls.append(True))
        return calls

    @pytest.fixture
    def prompts(self, monkeypatch):
        """Make input() fail the test unless a test installs its own answer."""
        asked: list[str] = []

        def unexpected(question=""):
            asked.append(question)
            raise AssertionError("unexpected prompt")

        monkeypatch.setattr("builtins.input", unexpected)
        return asked

    def answer(self, monkeypatch, reply: str) -> list[str]:
        """Install a canned input() reply and return the list of questions asked."""
        asked: list[str] = []

        def fake_input(question=""):
            asked.append(question)
            return reply

        monkeypatch.setattr("builtins.input", fake_input)
        return asked

    def test_missing_file_decline_exits_with_instructions(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        monkeypatch.setattr(bfc, "JSON_FILE", str(tmp_path / "market-price.json"))
        self.answer(monkeypatch, "n")
        with pytest.raises(SystemExit) as info:
            bfc.main()
        assert info.value.code == 1
        err = capsys.readouterr().err
        assert "market-price.json" in err
        assert "blockchain.com" in err
        assert shown == []

    def test_missing_file_accept_downloads_then_plots(
        self, tmp_path, monkeypatch, shown
    ):
        target = tmp_path / "market-price.json"
        monkeypatch.setattr(bfc, "JSON_FILE", str(target))
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", fake_urlopen(api_payload(1.0, 10.0))
        )
        self.answer(monkeypatch, "y")
        bfc.main()
        assert target.exists()
        assert shown == [True]

    def test_missing_file_download_failure_exits_with_instructions(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        monkeypatch.setattr(bfc, "JSON_FILE", str(tmp_path / "market-price.json"))
        monkeypatch.setattr(bfc.urllib.request, "urlopen", failing_urlopen)
        self.answer(monkeypatch, "y")
        with pytest.raises(SystemExit) as info:
            bfc.main()
        assert info.value.code == 1
        err = capsys.readouterr().err
        assert "could not download" in err
        assert "blockchain.com" in err
        assert shown == []

    def test_stale_file_decline_plots_old_data(self, tmp_path, monkeypatch, shown):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        set_mtime(data, dt.datetime.now() - dt.timedelta(days=3))
        monkeypatch.setattr(bfc, "JSON_FILE", str(data))
        asked = self.answer(monkeypatch, "n")
        bfc.main()
        assert len(asked) == 1
        assert shown == [True]

    def test_stale_file_download_failure_warns_and_plots(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        set_mtime(data, dt.datetime.now() - dt.timedelta(days=3))
        monkeypatch.setattr(bfc, "JSON_FILE", str(data))
        monkeypatch.setattr(bfc.urllib.request, "urlopen", failing_urlopen)
        self.answer(monkeypatch, "y")
        bfc.main()
        assert "Warning" in capsys.readouterr().err
        assert shown == [True]

    def test_current_file_never_prompts(self, tmp_path, monkeypatch, shown, prompts):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0, 100.0))
        monkeypatch.setattr(bfc, "JSON_FILE", str(data))
        bfc.main()
        assert prompts == []
        assert shown == [True]

    def test_stale_file_accept_replaces_it(self, tmp_path, monkeypatch, shown):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0))
        set_mtime(data, dt.datetime.now() - dt.timedelta(days=3))
        monkeypatch.setattr(bfc, "JSON_FILE", str(data))
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", fake_urlopen(api_payload(5.0, 9.0))
        )
        self.answer(monkeypatch, "y")
        bfc.main()
        assert bfc.load_price_data(data)["Close"].tolist() == [5.0, 9.0]
        assert bfc.is_data_current(str(data))
        assert shown == [True]

    def test_stale_file_unusable_download_keeps_old_data(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        data = write_json(tmp_path / "market-price.json", series(1.0, 10.0))
        set_mtime(data, dt.datetime.now() - dt.timedelta(days=3))
        before = data.read_text(encoding="utf-8")
        monkeypatch.setattr(bfc, "JSON_FILE", str(data))
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", fake_urlopen(api_payload(0, 0))
        )
        self.answer(monkeypatch, "y")
        bfc.main()
        assert data.read_text(encoding="utf-8") == before
        assert "Warning" in capsys.readouterr().err
        assert shown == [True]

    def test_eof_at_prompt_with_missing_file_exits(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        monkeypatch.setattr(bfc, "JSON_FILE", str(tmp_path / "market-price.json"))

        def raise_eof(*_a):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        with pytest.raises(SystemExit) as info:
            bfc.main()
        assert info.value.code == 1
        assert "blockchain.com" in capsys.readouterr().err
        assert shown == []

    def test_corrupt_file_decline_exits_with_hint(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        bad = tmp_path / "market-price.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(bfc, "JSON_FILE", str(bad))
        asked = self.answer(monkeypatch, "n")
        with pytest.raises(SystemExit) as info:
            bfc.main()
        assert info.value.code == 1
        err = capsys.readouterr().err
        assert "not valid JSON" in err
        assert "Delete or replace" in err
        assert len(asked) == 1
        assert shown == []

    def test_empty_file_decline_exits_with_hint(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        bad = tmp_path / "market-price.json"
        bad.write_text("", encoding="utf-8")
        monkeypatch.setattr(bfc, "JSON_FILE", str(bad))
        self.answer(monkeypatch, "n")
        with pytest.raises(SystemExit) as info:
            bfc.main()
        assert info.value.code == 1
        assert "Delete or replace" in capsys.readouterr().err

    def test_corrupt_file_download_failure_exits_with_hint(
        self, tmp_path, monkeypatch, capsys, shown
    ):
        bad = tmp_path / "market-price.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(bfc, "JSON_FILE", str(bad))
        monkeypatch.setattr(bfc.urllib.request, "urlopen", failing_urlopen)
        self.answer(monkeypatch, "y")
        with pytest.raises(SystemExit) as info:
            bfc.main()
        assert info.value.code == 1
        err = capsys.readouterr().err
        assert "could not download" in err
        assert "Delete or replace" in err
        assert shown == []

    def test_corrupt_file_download_success_plots(
        self, tmp_path, monkeypatch, shown
    ):
        bad = tmp_path / "market-price.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(bfc, "JSON_FILE", str(bad))
        monkeypatch.setattr(
            bfc.urllib.request, "urlopen", fake_urlopen(api_payload(3.0, 4.0))
        )
        self.answer(monkeypatch, "y")
        bfc.main()
        assert bfc.load_price_data(bad)["Close"].tolist() == [3.0, 4.0]
        assert shown == [True]
