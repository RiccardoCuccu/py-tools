"""Tests for price_data: price-file parsing and validation, API conversion, download.

The real market-price.json is never read: every test builds its own data in tmp_path
and HTTP is faked.
"""

import datetime as dt
import json

import pandas as pd
import pytest

import price_data
import utils
from helpers import (
    MS_PER_DAY,
    FakeResponse,
    api_payload,
    failing_urlopen,
    fake_urlopen,
    series,
    set_mtime,
    write_json,
)


class TestLoadPriceData:
    def test_basic_parse(self, tmp_path):
        path = write_json(tmp_path / "p.json", series(10.0, 20.0, 30.0))
        df = price_data.load_price_data(path)
        assert list(df.columns) == ["Date", "Close"]
        assert df["Close"].tolist() == [10.0, 20.0, 30.0]
        assert df["Date"].iloc[0] == pd.Timestamp("1970-01-01")
        assert df["Date"].iloc[1] == pd.Timestamp("1970-01-02")

    def test_zero_and_negative_prices_dropped(self, tmp_path):
        path = write_json(tmp_path / "p.json", series(0, 0, 5.0, -1, 7.0))
        assert price_data.load_price_data(path)["Close"].tolist() == [5.0, 7.0]

    def test_rows_sorted_by_date(self, tmp_path):
        payload = {
            "market-price": [
                {"x": 2 * MS_PER_DAY, "y": 3.0},
                {"x": 0, "y": 1.0},
                {"x": MS_PER_DAY, "y": 2.0},
            ]
        }
        df = price_data.load_price_data(write_json(tmp_path / "p.json", payload))
        assert df["Close"].tolist() == [1.0, 2.0, 3.0]
        assert df["Date"].is_monotonic_increasing

    def test_null_prices_are_dropped(self, tmp_path):
        payload = {"market-price": [{"x": 0, "y": None}, {"x": MS_PER_DAY, "y": 4.0}]}
        df = price_data.load_price_data(write_json(tmp_path / "p.json", payload))
        assert df["Close"].tolist() == [4.0]

    def test_all_zero_prices_rejected(self, tmp_path):
        path = write_json(tmp_path / "p.json", series(0, 0, 0))
        with pytest.raises(ValueError, match="no positive prices"):
            price_data.load_price_data(path)

    def test_empty_series_rejected(self, tmp_path):
        path = write_json(tmp_path / "p.json", {"market-price": []})
        with pytest.raises(ValueError):
            price_data.load_price_data(path)

    def test_missing_series_key_rejected(self, tmp_path):
        path = write_json(tmp_path / "p.json", {"other": []})
        with pytest.raises(ValueError, match="market-price"):
            price_data.load_price_data(path)

    def test_top_level_list_rejected(self, tmp_path):
        path = write_json(tmp_path / "p.json", [1, 2, 3])
        with pytest.raises(ValueError):
            price_data.load_price_data(path)

    def test_missing_fields_rejected(self, tmp_path):
        path = write_json(tmp_path / "p.json", {"market-price": [{"a": 1}]})
        with pytest.raises(ValueError, match="fields"):
            price_data.load_price_data(path)

    def test_invalid_json_rejected(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            price_data.load_price_data(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            price_data.load_price_data(tmp_path / "missing.json")


class TestDownloadPriceData:
    def test_converts_seconds_to_ms_and_loads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", fake_urlopen(api_payload(5.0, 7.0))
        )
        target = tmp_path / "market-price.json"
        price_data.download_price_data(str(target))
        saved = json.loads(target.read_text(encoding="utf-8"))
        assert saved == {
            "market-price": [
                {"x": 86_400_000, "y": 5.0},
                {"x": 172_800_000, "y": 7.0},
            ]
        }
        assert price_data.load_price_data(target)["Close"].tolist() == [5.0, 7.0]
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
        monkeypatch.setattr(utils.urllib.request, "urlopen", fake_urlopen(payload))
        with pytest.raises(ValueError):
            price_data.download_price_data(str(target))
        assert target.read_text(encoding="utf-8") == before
        assert list(tmp_path.iterdir()) == [target]

    def test_non_json_response_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", lambda *a, **k: FakeResponse(b"<html>")
        )
        with pytest.raises(ValueError, match="not valid JSON"):
            price_data.download_price_data(str(tmp_path / "market-price.json"))

    def test_network_error_keeps_existing_file(self, tmp_path, monkeypatch):
        target = write_json(tmp_path / "market-price.json", series(1.0))
        before = target.read_text(encoding="utf-8")
        monkeypatch.setattr(utils.urllib.request, "urlopen", failing_urlopen)
        with pytest.raises(ConnectionError):
            price_data.download_price_data(str(target))
        assert target.read_text(encoding="utf-8") == before
        assert list(tmp_path.iterdir()) == [target]

    @pytest.mark.parametrize(
        "x_value",
        [float("inf"), float("nan"), "5", None, True, [1]],
        ids=["inf", "nan", "string", "null", "bool", "list"],
    )
    def test_malformed_timestamp_rejected(self, tmp_path, monkeypatch, x_value):
        payload = {"status": "ok", "values": [{"x": x_value, "y": 1.0}]}
        monkeypatch.setattr(utils.urllib.request, "urlopen", fake_urlopen(payload))
        target = tmp_path / "market-price.json"
        with pytest.raises(ValueError, match="malformed price entries"):
            price_data.download_price_data(str(target))
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize("price", [0, None, "abc"], ids=["zero", "null", "text"])
    def test_unusable_prices_keep_existing_file(self, tmp_path, monkeypatch, price):
        target = write_json(tmp_path / "market-price.json", series(1.0))
        before = target.read_text(encoding="utf-8")
        payload = {"status": "ok", "values": [{"x": 86_400, "y": price}]}
        monkeypatch.setattr(utils.urllib.request, "urlopen", fake_urlopen(payload))
        with pytest.raises(ValueError, match="unusable"):
            price_data.download_price_data(str(target))
        assert target.read_text(encoding="utf-8") == before
        assert list(tmp_path.iterdir()) == [target]

    def test_oversized_response_rejected(self, tmp_path, monkeypatch):
        body = json.dumps(api_payload(1.0, 2.0, 3.0)).encode("utf-8")
        monkeypatch.setattr(utils, "MAX_DOWNLOAD_BYTES", len(body) - 1)
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", lambda *a, **k: FakeResponse(body)
        )
        with pytest.raises(ValueError, match="exceeds"):
            price_data.download_price_data(str(tmp_path / "market-price.json"))
        assert list(tmp_path.iterdir()) == []

    def test_response_at_size_cap_accepted(self, tmp_path, monkeypatch):
        body = json.dumps(api_payload(1.0, 2.0)).encode("utf-8")
        monkeypatch.setattr(utils, "MAX_DOWNLOAD_BYTES", len(body))
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", lambda *a, **k: FakeResponse(body)
        )
        target = tmp_path / "market-price.json"
        price_data.download_price_data(str(target))
        assert target.exists()

    def test_write_failure_cleans_temp_file(self, tmp_path, monkeypatch):
        target = write_json(tmp_path / "market-price.json", series(1.0))
        monkeypatch.setattr(
            utils.urllib.request, "urlopen", fake_urlopen(api_payload(2.0))
        )

        def boom(*_a, **_k):
            raise PermissionError("locked")

        monkeypatch.setattr(utils.os, "replace", boom)
        with pytest.raises(PermissionError):
            price_data.download_price_data(str(target))
        assert list(tmp_path.iterdir()) == [target]


class TestIsDataCurrent:
    def test_missing_file(self, tmp_path):
        assert price_data.is_data_current(str(tmp_path / "nope.json")) is False

    def test_modified_today(self, tmp_path):
        path = write_json(tmp_path / "p.json", series(1.0))
        assert price_data.is_data_current(str(path)) is True

    def test_modified_earlier(self, tmp_path):
        path = write_json(tmp_path / "p.json", series(1.0))
        set_mtime(path, dt.datetime.now() - dt.timedelta(days=2))
        assert price_data.is_data_current(str(path)) is False


class TestEnsurePriceDataResult:
    def _stale(self, tmp_path):
        path = write_json(tmp_path / "p.json", series(1.0, 2.0))
        set_mtime(path, dt.datetime.now() - dt.timedelta(days=2))
        return path

    def test_current_file_returns_false_without_asking(self, tmp_path, monkeypatch):
        path = write_json(tmp_path / "p.json", series(1.0))
        monkeypatch.setattr("builtins.input", lambda *_a: pytest.fail("prompted"))
        assert price_data.ensure_price_data(str(path)) is False

    def test_declined_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *_a: "n")
        assert price_data.ensure_price_data(str(self._stale(tmp_path))) is False

    def test_accepted_returns_true_even_when_download_fails(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("builtins.input", lambda *_a: "y")
        monkeypatch.setattr(utils.urllib.request, "urlopen", failing_urlopen)
        assert price_data.ensure_price_data(str(self._stale(tmp_path))) is True
