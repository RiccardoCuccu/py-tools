"""Tests for watch_later with yt-dlp fully mocked."""

import pytest
from yt_dlp.utils import DownloadError

import watch_later
from watch_later import WatchLaterError


class _FakeYDL:
    """Stand-in for yt_dlp.YoutubeDL recording its options and URL."""

    instances: list["_FakeYDL"] = []
    result: object = {"entries": []}

    def __init__(self, options):
        self.options = options
        self.urls = []
        _FakeYDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        self.urls.append((url, download))
        if isinstance(_FakeYDL.result, Exception):
            raise _FakeYDL.result
        return _FakeYDL.result


@pytest.fixture(autouse=True)
def fake_ydl(monkeypatch):
    """Replace yt_dlp.YoutubeDL so no real extraction or network happens."""
    _FakeYDL.instances = []
    _FakeYDL.result = {"entries": []}
    monkeypatch.setattr(watch_later.yt_dlp, "YoutubeDL", _FakeYDL)
    return _FakeYDL


def test_build_options_uses_browser_cookies():
    options = watch_later.build_options("chrome", "")
    assert options["cookiesfrombrowser"] == ("chrome", None, None, None)
    assert options["extract_flat"] == "in_playlist"
    assert "cookiefile" not in options


def test_build_options_cookies_file_wins_over_browser(tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    options = watch_later.build_options("chrome", str(cookies))
    assert options["cookiefile"] == str(cookies)
    assert "cookiesfrombrowser" not in options


def test_build_options_missing_cookies_file_raises(tmp_path):
    with pytest.raises(WatchLaterError, match="not found"):
        watch_later.build_options("", str(tmp_path / "nope.txt"))


def test_build_options_without_cookie_source_raises():
    with pytest.raises(WatchLaterError, match="no cookie source"):
        watch_later.build_options("", "")


def test_fetch_returns_ids_and_skips_bad_entries(fake_ydl):
    fake_ydl.result = {"entries": [{"id": "v1"}, None, {"title": "x"}, {"id": "v2"}]}
    assert watch_later.fetch_watch_later_ids("chrome", "") == ["v1", "v2"]
    assert fake_ydl.instances[0].urls == [(":ytwatchlater", False)]


def test_fetch_handles_empty_result(fake_ydl):
    fake_ydl.result = None
    assert watch_later.fetch_watch_later_ids("chrome", "") == []


@pytest.mark.parametrize("error", [DownloadError("login required"), OSError("locked")])
def test_fetch_wraps_failures(fake_ydl, error):
    fake_ydl.result = error
    with pytest.raises(WatchLaterError):
        watch_later.fetch_watch_later_ids("chrome", "")
