"""Tests for bitcoin_fibonacci_log_chart: price-file parsing and validation, Fibonacci
level math, halving filtering, chart construction (headless Agg backend), and main().
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
import matplotlib.pyplot as plt
import pandas as pd
import pytest

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


class TestFibonacciPrices:
    def test_levels_measured_down_from_high(self):
        prices = bfc.compute_fibonacci_prices(100.0, 0.0)
        assert prices == pytest.approx([76.4, 61.8, 50.0, 38.2, 21.4])

    def test_nonzero_low(self):
        prices = bfc.compute_fibonacci_prices(200.0, 100.0, [0.5])
        assert prices == [150.0]

    def test_flat_range_collapses_to_single_price(self):
        assert bfc.compute_fibonacci_prices(50.0, 50.0) == [50.0] * len(bfc.FIBONACCI_LEVELS)

    def test_levels_are_ordered_descending_and_within_range(self):
        prices = bfc.compute_fibonacci_prices(1000.0, 10.0)
        assert prices == sorted(prices, reverse=True)
        assert all(10.0 <= p <= 1000.0 for p in prices)

    def test_default_levels_are_standard(self):
        assert bfc.FIBONACCI_LEVELS == [0.236, 0.382, 0.5, 0.618, 0.786]


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

    def test_log_scale_and_fib_lines(self, tmp_path):
        df = self._df(tmp_path, series(10.0, 100.0, 1000.0))
        fig = bfc.build_chart(df)
        ax = fig.axes[0]
        assert ax.get_yscale() == "log"
        legend = ax.get_legend()
        assert legend is not None
        legend_labels = [t.get_text() for t in legend.get_texts()]
        assert len([lbl for lbl in legend_labels if lbl.startswith("Fib ")]) == len(
            bfc.FIBONACCI_LEVELS
        )
        assert "Fib 23.6% (766 USD)" in legend_labels

    def test_halving_markers_only_when_in_data_range(self, tmp_path):
        inside = self._df(tmp_path, series(1.0, 2.0, 3.0, start_ms=EPOCH_2012_12_01_MS - 5 * MS_PER_DAY))
        fig = bfc.build_chart(inside)
        texts = [t.get_text() for t in fig.axes[0].texts]
        assert texts == ["2012-11-28"]

        outside = self._df(tmp_path, series(1.0, 2.0, start_ms=EPOCH_2012_12_01_MS))
        assert list(bfc.build_chart(outside).axes[0].texts) == []

    def test_single_point_does_not_crash(self, tmp_path):
        df = self._df(tmp_path, series(42.0))
        assert bfc.build_chart(df).axes


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
