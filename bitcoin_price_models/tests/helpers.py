"""Shared test helpers: fake price payloads, fake HTTP responses and file times."""

import datetime as dt
import http.client
import json
import os
import urllib.error
from pathlib import Path

MS_PER_DAY = 86_400_000
EPOCH_2012_12_01_MS = int(
    dt.datetime(2012, 12, 1, tzinfo=dt.timezone.utc).timestamp() * 1000
)


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


# Real halving block times (unix seconds) keyed by height
HALVING_TIMESTAMPS = {
    210_000: 1_354_116_278,
    420_000: 1_468_082_773,
    630_000: 1_589_225_023,
    840_000: 1_713_571_767,
}
TIP_URL = "https://mempool.space/api/blocks/tip/height"
BLOCK_URL_PREFIX = "https://mempool.space/api/v1/blocks/"


def mempool_fetcher(tip: int, requested: list[str] | None = None):
    """
    Return a fetch_bytes replacement that serves the mempool.space endpoints.

    Every requested URL is appended to requested, when given.
    """

    def fetch(url: str) -> bytes:
        if requested is not None:
            requested.append(url)
        if url == TIP_URL:
            return str(tip).encode("ascii")
        height = int(url.removeprefix(BLOCK_URL_PREFIX))
        block = {"height": height, "timestamp": HALVING_TIMESTAMPS[height]}
        return json.dumps([block]).encode("utf-8")

    return fetch


def set_mtime(path: Path, when: dt.datetime) -> None:
    """Set the modification time of path to when (local time)."""
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))
