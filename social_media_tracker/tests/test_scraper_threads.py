"""Tests for scraper_threads: username extraction, hidden-JSON extraction, recursive
follower search, and the retry/fallback logic of get_followers (HTTP is faked).
"""

from __future__ import annotations

import json

import pytest
import requests

import scraper_threads as th


class FakeResponse:
    def __init__(self, text: str = "", status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def script(payload) -> str:
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return f'<script type="application/json" data-content-len="12" data-sjs>{body}</script>'


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.threads.com/@alice", "alice"),
        ("https://www.threads.com/@alice/", "alice"),
        ("https://www.threads.net/@alice?x=1", "alice"),
        ("https://www.threads.com/alice", "alice"),
        ("https://www.threads.com/", ""),
    ],
)
def test_extract_username(url: str, expected: str) -> None:
    assert th.extract_username(url) == expected


def test_extract_all_hidden_data_returns_every_valid_block() -> None:
    html = script({"a": 1}) + "<p>x</p>" + script({"b": 2})
    assert th.extract_all_hidden_data(html) == [{"a": 1}, {"b": 2}]


def test_extract_all_hidden_data_skips_malformed_block() -> None:
    html = script("{broken") + script({"ok": True})
    assert th.extract_all_hidden_data(html) == [{"ok": True}]


def test_extract_hidden_data_none_when_absent() -> None:
    assert th.extract_hidden_data("<html></html>") is None
    assert th.extract_hidden_data(script({"a": 1})) == {"a": 1}


def test_find_follower_count_searches_nested_structures() -> None:
    data = {"x": [{"y": {"user": {"follower_count": 321}}}]}
    assert th.find_follower_count(data) == 321


def test_find_follower_count_ignores_non_int_values() -> None:
    assert th.find_follower_count({"follower_count": "12"}) is None
    assert th.find_follower_count({"a": [1, 2, {"b": None}]}) is None
    assert th.find_follower_count({}) is None


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []
    monkeypatch.setattr(th.time, "sleep", delays.append)
    return delays


def test_get_followers_from_hidden_json_in_later_block(
    monkeypatch: pytest.MonkeyPatch, no_sleep
) -> None:
    html = script({"nothing": 1}) + script({"user": {"follower_count": 55}})
    urls: list[str] = []

    def fake_get(url, headers, timeout):
        urls.append(url)
        return FakeResponse(html)

    monkeypatch.setattr(th.requests, "get", fake_get)
    result = th.get_followers("https://www.threads.com/@alice")
    assert result == {"username": "alice", "followers": 55}
    assert urls == ["https://www.threads.com/@alice"]


def test_get_followers_regex_fallback(monkeypatch: pytest.MonkeyPatch, no_sleep) -> None:
    html = '<script>{"follower_count": 0, "x": {"follower_count": 77}}</script>'
    monkeypatch.setattr(th.requests, "get", lambda *a, **k: FakeResponse(html))
    assert th.get_followers("https://www.threads.com/@alice")["followers"] == 77


def test_get_followers_retries_then_returns_none(
    monkeypatch: pytest.MonkeyPatch, no_sleep
) -> None:
    calls: list[int] = []

    def fake_get(*a, **k):
        calls.append(1)
        return FakeResponse("<html>nothing</html>")

    monkeypatch.setattr(th.requests, "get", fake_get)
    result = th.get_followers("https://www.threads.com/@alice", max_retries=3, retry_delay=4)
    assert result == {"username": "alice", "followers": None}
    assert len(calls) == 3
    assert no_sleep == [4, 4]


def test_get_followers_http_error_returns_none_after_retries(
    monkeypatch: pytest.MonkeyPatch, no_sleep
) -> None:
    monkeypatch.setattr(th.requests, "get", lambda *a, **k: FakeResponse(status=429))
    result = th.get_followers("https://www.threads.com/@alice", max_retries=2, retry_delay=1)
    assert result == {"username": "alice", "followers": None}
    assert no_sleep == [1]


def test_get_followers_recovers_after_transient_error(
    monkeypatch: pytest.MonkeyPatch, no_sleep
) -> None:
    responses = iter([FakeResponse(status=500), FakeResponse(script({"follower_count": 9}))])
    monkeypatch.setattr(th.requests, "get", lambda *a, **k: next(responses))
    assert th.get_followers("https://www.threads.com/@a", retry_delay=0)["followers"] == 9


def test_get_followers_empty_username_makes_no_request(
    monkeypatch: pytest.MonkeyPatch, no_sleep
) -> None:
    monkeypatch.setattr(th.requests, "get", lambda *a, **k: pytest.fail("no request expected"))
    assert th.get_followers("https://www.threads.com/") == {"username": "", "followers": None}


def test_get_followers_encodes_username_in_url(
    monkeypatch: pytest.MonkeyPatch, no_sleep
) -> None:
    urls: list[str] = []

    def fake_get(url, **k):
        urls.append(url)
        return FakeResponse(script({"follower_count": 1}))

    monkeypatch.setattr(th.requests, "get", fake_get)
    th.get_followers("https://www.threads.com/@a b?x", max_retries=1)
    assert urls == ["https://www.threads.com/@a%20b"]
