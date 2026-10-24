"""Tests for scraper_youtube: subscriber extraction, hidden counts, retry behaviour and
terminal errors, with yt-dlp replaced by a fake (no network access).
"""

from __future__ import annotations

import pytest

import scraper_youtube as yt


def fake_ydl_factory(outcomes: list):
    """Build a YoutubeDL replacement that yields each outcome (value or exception) in turn."""
    pending = list(outcomes)
    created: list[dict] = []

    class FakeYoutubeDL:
        def __init__(self, opts: dict) -> None:
            created.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True):
            outcome = pending.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    FakeYoutubeDL.created = created  # type: ignore[attr-defined]
    return FakeYoutubeDL


@pytest.fixture(autouse=True)
def available_and_no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []
    monkeypatch.setattr(yt, "AVAILABLE", True)
    monkeypatch.setattr(yt.time, "sleep", delays.append)
    return delays


def test_returns_subscriber_count_and_channel_name(monkeypatch: pytest.MonkeyPatch) -> None:
    info = {"channel_follower_count": 1500, "channel": "My Channel", "channel_id": "UC1"}
    monkeypatch.setattr(yt, "YoutubeDL", fake_ydl_factory([info]))
    assert yt.get_followers("https://youtube.com/@x") == {
        "username": "My Channel", "followers": 1500,
    }


def test_falls_back_to_channel_id_when_name_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    info = {"channel_follower_count": 3, "channel": "", "channel_id": "UC1"}
    monkeypatch.setattr(yt, "YoutubeDL", fake_ydl_factory([info]))
    assert yt.get_followers("u")["username"] == "UC1"


def test_hidden_subscriber_count_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    info = {"channel": "Hidden"}
    ydl = fake_ydl_factory([info])
    monkeypatch.setattr(yt, "YoutubeDL", ydl)
    assert yt.get_followers("u") == {"username": "Hidden", "followers": None}


def test_retries_after_transient_error(
    monkeypatch: pytest.MonkeyPatch, available_and_no_sleep: list[float]
) -> None:
    info = {"channel_follower_count": 8, "channel": "C"}
    monkeypatch.setattr(yt, "YoutubeDL", fake_ydl_factory([RuntimeError("timeout"), info]))
    result = yt.get_followers("u", max_retries=3, retry_delay=6)
    assert result["followers"] == 8
    assert available_and_no_sleep == [6]


def test_gives_up_after_max_retries(
    monkeypatch: pytest.MonkeyPatch, available_and_no_sleep: list[float]
) -> None:
    errors = [RuntimeError("x")] * 3
    monkeypatch.setattr(yt, "YoutubeDL", fake_ydl_factory(errors))
    result = yt.get_followers("u", max_retries=3, retry_delay=2)
    assert result == {"username": "", "followers": None}
    assert available_and_no_sleep == [2, 2]


@pytest.mark.parametrize("message", ["Private video", "This channel does not exist"])
def test_terminal_errors_are_not_retried(
    monkeypatch: pytest.MonkeyPatch, available_and_no_sleep: list[float], message: str
) -> None:
    monkeypatch.setattr(yt, "YoutubeDL", fake_ydl_factory([RuntimeError(message)]))
    result = yt.get_followers("u", max_retries=3)
    assert result == {"username": "", "followers": None}
    assert available_and_no_sleep == []


def test_empty_info_is_retried(
    monkeypatch: pytest.MonkeyPatch, available_and_no_sleep: list[float]
) -> None:
    info = {"channel_follower_count": 4, "channel": "C"}
    monkeypatch.setattr(yt, "YoutubeDL", fake_ydl_factory([None, info]))
    assert yt.get_followers("u", max_retries=2, retry_delay=1)["followers"] == 4


def test_missing_yt_dlp_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yt, "AVAILABLE", False)
    assert yt.get_followers("u") == {"username": "", "followers": None}
