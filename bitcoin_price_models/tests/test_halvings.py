"""Tests for halvings: mempool.space parsing, the incremental cache, the next-halving
estimate and the never-crash fallbacks. HTTP is faked by patching fetch_bytes in the
halvings module; every file lives in tmp_path.
"""

import datetime as dt
import json

import pytest

import halvings
from helpers import (
    BLOCK_URL_PREFIX,
    HALVING_TIMESTAMPS,
    TIP_URL,
    mempool_fetcher,
    write_json,
)

NOW = dt.datetime(2026, 10, 24, 12, 0, tzinfo=dt.timezone.utc)
TIP = 850_000
EXPECTED_DATES = [
    dt.datetime(2012, 11, 28, 15, 24, 38),
    dt.datetime(2016, 7, 9, 16, 46, 13),
    dt.datetime(2020, 5, 11, 19, 23, 43),
    dt.datetime(2024, 4, 20, 0, 9, 27),
]


def block_url(height: int) -> str:
    """Return the block endpoint URL for height."""
    return f"{BLOCK_URL_PREFIX}{height}"


def serve(monkeypatch, tip: int = TIP) -> list[str]:
    """Patch fetch_bytes with the fake mempool; return the list of requested URLs."""
    requested: list[str] = []
    monkeypatch.setattr(halvings, "fetch_bytes", mempool_fetcher(tip, requested))
    return requested


def serve_raw(monkeypatch, tip: bytes, block: bytes) -> None:
    """Patch fetch_bytes to return fixed raw bodies for the tip and block endpoints."""
    monkeypatch.setattr(
        halvings, "fetch_bytes", lambda url: tip if url == TIP_URL else block
    )


def offline(monkeypatch) -> None:
    """Patch fetch_bytes to fail like a dead network."""

    def fail(_url: str) -> bytes:
        raise ConnectionError("could not download: offline")

    monkeypatch.setattr(halvings, "fetch_bytes", fail)


def block_body(height: int, timestamp: object) -> bytes:
    """Return a block endpoint body for height with the given timestamp."""
    return json.dumps([{"height": height, "timestamp": timestamp}]).encode("utf-8")


class TestHeights:
    @pytest.mark.parametrize(
        ("tip", "expected"),
        [
            (0, []),
            (209_999, []),
            (210_000, [210_000]),
            (839_999, [210_000, 420_000, 630_000]),
            (850_000, [210_000, 420_000, 630_000, 840_000]),
        ],
    )
    def test_past_heights_are_multiples_at_or_below_tip(self, tip, expected):
        assert halvings.halving_heights(tip) == expected

    @pytest.mark.parametrize(
        ("tip", "expected"),
        [(0, 210_000), (209_999, 210_000), (210_000, 420_000), (850_000, 1_050_000)],
    )
    def test_next_height_is_first_multiple_above_tip(self, tip, expected):
        assert halvings.next_halving_height(tip) == expected


class TestEstimate:
    def test_estimate_for_fixed_tip_and_now(self):
        record = halvings.estimate_next_halving(TIP, NOW)
        remaining_seconds = (1_050_000 - TIP) * 600
        assert record == {
            "height": 1_050_000,
            "estimated_timestamp": int(NOW.timestamp()) + remaining_seconds,
            "tip_height": TIP,
            "computed_at": int(NOW.timestamp()),
        }

    def test_estimate_lands_in_expected_year(self):
        record = halvings.estimate_next_halving(TIP, NOW)
        estimated = dt.datetime.fromtimestamp(
            record["estimated_timestamp"], dt.timezone.utc
        )
        assert estimated == NOW + dt.timedelta(seconds=200_000 * 600)


class TestUpdateAndLoad:
    def test_update_downloads_all_and_cache_round_trips(self, tmp_path, monkeypatch):
        serve(monkeypatch)
        cache = tmp_path / "halvings.json"
        halvings.update_halvings(cache, NOW)

        info = halvings.load_halvings(cache)
        assert info.past == EXPECTED_DATES
        estimate = halvings.estimate_next_halving(TIP, NOW)
        assert info.next_estimate == dt.datetime.fromtimestamp(
            estimate["estimated_timestamp"], dt.timezone.utc
        ).replace(tzinfo=None)

        stored = json.loads(cache.read_text(encoding="utf-8"))
        assert stored["past"] == [
            {"height": h, "timestamp": ts} for h, ts in HALVING_TIMESTAMPS.items()
        ]
        assert stored["next"] == estimate

    def test_incremental_fetch_requests_only_missing_heights(
        self, tmp_path, monkeypatch
    ):
        cache = tmp_path / "halvings.json"
        serve(monkeypatch, tip=700_000)
        halvings.update_halvings(cache, NOW)

        requested = serve(monkeypatch, tip=TIP)
        halvings.update_halvings(cache, NOW)

        assert requested == [TIP_URL, block_url(840_000)]
        assert len(halvings.load_halvings(cache).past) == 4

    def test_nothing_missing_requests_only_the_tip(self, tmp_path, monkeypatch):
        cache = tmp_path / "halvings.json"
        serve(monkeypatch)
        halvings.update_halvings(cache, NOW)

        requested = serve(monkeypatch)
        halvings.update_halvings(cache, NOW)
        assert requested == [TIP_URL]

    def test_estimate_is_recomputed_on_refresh(self, tmp_path, monkeypatch):
        cache = tmp_path / "halvings.json"
        serve(monkeypatch)
        halvings.update_halvings(cache, NOW)
        later = NOW + dt.timedelta(days=10)
        halvings.update_halvings(cache, later)
        stored = json.loads(cache.read_text(encoding="utf-8"))
        assert stored["next"]["computed_at"] == int(later.timestamp())

    def test_tip_below_first_halving_has_no_past(self, tmp_path, monkeypatch):
        cache = tmp_path / "halvings.json"
        serve(monkeypatch, tip=100)
        halvings.update_halvings(cache, NOW)
        info = halvings.load_halvings(cache)
        assert info.past == []
        assert info.next_estimate is not None

    def test_load_missing_cache_is_empty_without_warning(self, tmp_path, capsys):
        info = halvings.load_halvings(tmp_path / "halvings.json")
        assert info == halvings.HalvingInfo(past=[], next_estimate=None)
        assert capsys.readouterr().err == ""

    def test_load_corrupt_cache_is_empty_with_warning(self, tmp_path, capsys):
        cache = tmp_path / "halvings.json"
        cache.write_text("{not json", encoding="utf-8")
        info = halvings.load_halvings(cache)
        assert info == halvings.HalvingInfo(past=[], next_estimate=None)
        assert "Warning" in capsys.readouterr().err

    def test_rejected_update_keeps_the_old_cache(self, tmp_path, monkeypatch):
        cache = tmp_path / "halvings.json"
        serve(monkeypatch, tip=700_000)
        halvings.update_halvings(cache, NOW)
        before = cache.read_text(encoding="utf-8")

        serve_raw(monkeypatch, b"850000", block_body(840_000, 5))
        with pytest.raises(ValueError, match="plausible"):
            halvings.update_halvings(cache, NOW)
        assert cache.read_text(encoding="utf-8") == before
        assert sorted(p.name for p in tmp_path.iterdir()) == ["halvings.json"]


class TestEnsure:
    def test_missing_cache_downloads_without_asking_and_logs(
        self, tmp_path, monkeypatch, capsys
    ):
        serve(monkeypatch)
        monkeypatch.setattr("builtins.input", lambda *_a: pytest.fail("prompted"))
        cache = tmp_path / "halvings.json"
        halvings.ensure_halvings(cache, refresh=False)
        assert "Downloading halvings" in capsys.readouterr().out
        assert halvings.load_halvings(cache).past == EXPECTED_DATES

    def test_usable_cache_without_refresh_makes_no_request(
        self, tmp_path, monkeypatch
    ):
        cache = tmp_path / "halvings.json"
        serve(monkeypatch)
        halvings.update_halvings(cache, NOW)
        requested = serve(monkeypatch)
        halvings.ensure_halvings(cache, refresh=False)
        assert requested == []

    def test_refresh_updates_a_usable_cache(self, tmp_path, monkeypatch):
        cache = tmp_path / "halvings.json"
        serve(monkeypatch, tip=700_000)
        halvings.update_halvings(cache, NOW)
        serve(monkeypatch)
        halvings.ensure_halvings(cache, refresh=True)
        assert len(halvings.load_halvings(cache).past) == 4

    def test_corrupt_cache_is_refetched_in_full(self, tmp_path, monkeypatch):
        cache = tmp_path / "halvings.json"
        cache.write_text("{not json", encoding="utf-8")
        requested = serve(monkeypatch)
        halvings.ensure_halvings(cache, refresh=False)
        assert requested == [TIP_URL, *[block_url(h) for h in HALVING_TIMESTAMPS]]
        assert halvings.load_halvings(cache).past == EXPECTED_DATES

    def test_structurally_invalid_cache_is_refetched(self, tmp_path, monkeypatch):
        cache = write_json(tmp_path / "halvings.json", {"past": "x", "next": []})
        serve(monkeypatch)
        halvings.ensure_halvings(cache, refresh=False)
        assert halvings.load_halvings(cache).past == EXPECTED_DATES

    def test_network_failure_with_cache_falls_back_to_it(
        self, tmp_path, monkeypatch, capsys
    ):
        cache = tmp_path / "halvings.json"
        serve(monkeypatch)
        halvings.update_halvings(cache, NOW)
        before = cache.read_text(encoding="utf-8")

        offline(monkeypatch)
        halvings.ensure_halvings(cache, refresh=True)

        assert "Using the cached halvings" in capsys.readouterr().err
        assert cache.read_text(encoding="utf-8") == before
        assert halvings.load_halvings(cache).past == EXPECTED_DATES

    def test_network_failure_without_cache_yields_no_halvings(
        self, tmp_path, monkeypatch, capsys
    ):
        cache = tmp_path / "halvings.json"
        offline(monkeypatch)
        halvings.ensure_halvings(cache, refresh=False)

        assert "without halving lines" in capsys.readouterr().err
        assert not cache.exists()
        assert halvings.load_halvings(cache).past == []

    def test_malformed_response_without_cache_does_not_crash(
        self, tmp_path, monkeypatch, capsys
    ):
        cache = tmp_path / "halvings.json"
        serve_raw(monkeypatch, b"<html>", b"[]")
        halvings.ensure_halvings(cache, refresh=False)
        assert "Warning" in capsys.readouterr().err
        assert not cache.exists()


class TestResponseValidation:
    def test_tip_height_parses_plain_text(self, monkeypatch):
        serve_raw(monkeypatch, b"850123\n", b"")
        assert halvings.fetch_tip_height() == 850_123

    @pytest.mark.parametrize(
        "body",
        [b"", b"abc", b"-5", b"1.5", b"\xc2\xb2", b"99999999999", b'{"h": 1}'],
    )
    def test_tip_height_rejects_non_integers(self, monkeypatch, body):
        serve_raw(monkeypatch, body, b"")
        with pytest.raises(ValueError):
            halvings.fetch_tip_height()

    def test_block_timestamp_is_read_from_first_entry(self, monkeypatch):
        serve_raw(monkeypatch, b"", block_body(840_000, 1_713_571_767))
        assert halvings.fetch_block_timestamp(840_000) == 1_713_571_767

    def test_height_mismatch_is_rejected(self, monkeypatch):
        serve_raw(monkeypatch, b"", block_body(839_999, 1_713_571_767))
        with pytest.raises(ValueError, match="not for block 840000"):
            halvings.fetch_block_timestamp(840_000)

    @pytest.mark.parametrize(
        "body",
        [
            b"not json",
            b"",
            b"{}",
            b"[]",
            b"[1]",
            b'[{"height": 840000}]',
            b'[{"timestamp": 1713571767}]',
            b'[{"height": "840000", "timestamp": 1713571767}]',
            b'[{"height": 840000, "timestamp": "1713571767"}]',
            b'[{"height": 840000, "timestamp": true}]',
            b'[{"height": true, "timestamp": 1713571767}]',
            b'[{"height": 840000, "timestamp": 1.5}]',
            b'[{"height": 840000, "timestamp": 0}]',
            b'[{"height": 840000, "timestamp": 99999999999}]',
        ],
    )
    def test_malformed_block_response_is_rejected(self, monkeypatch, body):
        serve_raw(monkeypatch, b"", body)
        with pytest.raises(ValueError):
            halvings.fetch_block_timestamp(840_000)

    def test_network_error_propagates_as_connection_error(self, monkeypatch):
        offline(monkeypatch)
        with pytest.raises(ConnectionError):
            halvings.fetch_block_timestamp(840_000)


class TestCacheValidation:
    def _valid(self) -> dict:
        record = halvings.estimate_next_halving(TIP, NOW)
        return {
            "past": [{"height": h, "timestamp": ts} for h, ts in HALVING_TIMESTAMPS.items()],
            "next": record,
        }

    def test_valid_cache_loads(self, tmp_path):
        cache = write_json(tmp_path / "halvings.json", self._valid())
        assert halvings.load_halvings(cache).past == EXPECTED_DATES

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d["past"].reverse(),
            lambda d: d["past"].pop(),
            lambda d: d["past"][0].update(height=210_001),
            lambda d: d["past"][0].update(height=True),
            lambda d: d["past"][0].update(timestamp="x"),
            lambda d: d["past"][1].update(timestamp=d["past"][0]["timestamp"]),
            lambda d: d["past"].append(5),
            lambda d: d["next"].update(height=1_260_000),
            lambda d: d["next"].update(estimated_timestamp=None),
            lambda d: d["next"].update(tip_height=-1),
            lambda d: d.pop("next"),
            lambda d: d.update(past={}),
        ],
    )
    def test_invalid_cache_is_rejected(self, tmp_path, mutate):
        data = self._valid()
        mutate(data)
        cache = write_json(tmp_path / "halvings.json", data)
        with pytest.raises(ValueError):
            halvings._read_cache(cache)

    def test_non_dict_cache_is_rejected(self, tmp_path):
        cache = write_json(tmp_path / "halvings.json", [1, 2])
        with pytest.raises(ValueError):
            halvings._read_cache(cache)
