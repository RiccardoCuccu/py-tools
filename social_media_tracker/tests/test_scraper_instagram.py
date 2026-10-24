"""Tests for scraper_instagram: username extraction, follower-count parsing from HTML,
JSON-LD and span titles, the API/requests fetchers, and the retry/fallback orchestration.
All HTTP and browser access is faked.
"""

from __future__ import annotations

import json

import pytest
import requests

import scraper_instagram as ig


class FakeResponse:
    def __init__(self, text: str = "", payload=None, status: int = 200) -> None:
        self.text = text
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.instagram.com/alice/", "alice"),
        ("https://www.instagram.com/alice", "alice"),
        ("https://www.instagram.com/alice/?hl=en", "alice"),
        ("https://www.instagram.com/", ""),
        ("", ""),
    ],
)
def test_extract_username(url: str, expected: str) -> None:
    assert ig.extract_username(url) == expected


@pytest.mark.parametrize(
    "html, expected",
    [
        ('..."edge_followed_by":{"count":1390}...', 1390),
        ('"edge_followed_by" : { "count" : 42 }', 42),
        ('{"follower_count": 987}', 987),
        ('"edge_follow":{"count":55},"edge_followed_by":{"count":77}', 77),
        ('"edge_followed_by":{"count":0}', None),
        ('"edge_followed_by":{"count":5000000000}', None),
        ("<html>no data</html>", None),
        ("", None),
    ],
)
def test_parse_follower_count_regex(html: str, expected) -> None:
    assert ig._parse_follower_count(html) == expected


def ld_html(payload) -> str:
    return f'<script type="application/ld+json">{json.dumps(payload)}</script>'


def test_parse_follower_count_json_ld() -> None:
    payload = {"interactionStatistic": [
        {"interactionType": "https://schema.org/LikeAction", "userInteractionCount": 9},
        {"interactionType": "https://schema.org/FollowAction", "userInteractionCount": 321},
    ]}
    assert ig._parse_follower_count(ld_html(payload)) == 321


def test_parse_follower_count_json_ld_nested_author() -> None:
    payload = {"author": {"interactionStatistic": [
        {"interactionType": "FollowAction", "userInteractionCount": 12},
    ]}}
    assert ig._parse_follower_count(ld_html(payload)) == 12


@pytest.mark.parametrize(
    "payload",
    [[1, 2], {"interactionStatistic": "oops"}, {"interactionStatistic": [{"interactionType": 5}]},
     {"author": None}],
)
def test_parse_follower_count_json_ld_malformed_is_ignored(payload) -> None:
    assert ig._parse_follower_count(ld_html(payload)) is None


def test_parse_follower_count_invalid_json_ld_is_ignored() -> None:
    html = '<script type="application/ld+json">{broken</script>'
    assert ig._parse_follower_count(html) is None


@pytest.mark.parametrize(
    "title, expected",
    [("1,390", 1390), ("1.390", 1390), ("1 390", 1390), (" 42 ", 42), ("0", 0),
     ("1.5M", None), ("", None), ("Verified", None), ("-5", None)],
)
def test_parse_follower_title(title: str, expected) -> None:
    assert ig._parse_follower_title(title) == expected


# Fetchers

def test_fetch_with_api_success_and_encoded_username(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_get(url, headers, timeout):
        seen.update(url=url, headers=headers)
        return FakeResponse(payload={"data": {"user": {"edge_followed_by": {"count": 55}}}})

    monkeypatch.setattr(ig.requests, "get", fake_get)
    assert ig._fetch_with_api("a b&x=1") == 55
    assert "username=a%20b%26x%3D1" in seen["url"]
    assert seen["headers"]["x-ig-app-id"] == ig.INSTAGRAM_APP_ID


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(status=429),
        FakeResponse(payload={"data": {"user": None}}),
        FakeResponse(payload={}),
        FakeResponse(payload={"data": {"user": {"edge_followed_by": {"count": -1}}}}),
    ],
)
def test_fetch_with_api_failures_return_none(monkeypatch: pytest.MonkeyPatch, response) -> None:
    monkeypatch.setattr(ig.requests, "get", lambda *a, **k: response)
    assert ig._fetch_with_api("alice") is None


def test_fetch_with_api_network_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(ig.requests, "get", boom)
    assert ig._fetch_with_api("alice") is None


def test_fetch_with_requests_parses_page(monkeypatch: pytest.MonkeyPatch) -> None:
    html = '"edge_followed_by":{"count":10}'
    monkeypatch.setattr(ig.requests, "get", lambda *a, **k: FakeResponse(text=html))
    assert ig._fetch_with_requests("https://www.instagram.com/a/") == 10


def test_fetch_with_requests_http_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ig.requests, "get", lambda *a, **k: FakeResponse(status=403))
    assert ig._fetch_with_requests("https://www.instagram.com/a/") is None


def test_fetch_with_selenium_skipped_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ig, "SELENIUM_AVAILABLE", False)
    assert ig._fetch_with_selenium("https://www.instagram.com/a/") is None


# Orchestration

@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []
    monkeypatch.setattr(ig.time, "sleep", delays.append)
    return delays


def test_get_followers_uses_api_first(monkeypatch: pytest.MonkeyPatch, no_sleep) -> None:
    monkeypatch.setattr(ig, "_fetch_with_api", lambda u, d=False: 100)
    monkeypatch.setattr(ig, "_fetch_with_requests", lambda *a: pytest.fail("not needed"))
    monkeypatch.setattr(ig, "_fetch_with_selenium", lambda *a: pytest.fail("not needed"))
    result = ig.get_followers("https://www.instagram.com/alice/")
    assert result == {"username": "alice", "followers": 100}


def test_get_followers_falls_back_through_methods(monkeypatch: pytest.MonkeyPatch, no_sleep) -> None:
    monkeypatch.setattr(ig, "_fetch_with_api", lambda u, d=False: None)
    monkeypatch.setattr(ig, "_fetch_with_requests", lambda u, d=False: None)
    monkeypatch.setattr(ig, "_fetch_with_selenium", lambda u, d=False: 7)
    assert ig.get_followers("https://www.instagram.com/alice/")["followers"] == 7


def test_get_followers_retries_then_gives_up(monkeypatch: pytest.MonkeyPatch, no_sleep) -> None:
    attempts: list[int] = []
    monkeypatch.setattr(ig, "_fetch_with_api", lambda u, d=False: attempts.append(1))
    monkeypatch.setattr(ig, "_fetch_with_requests", lambda u, d=False: None)
    monkeypatch.setattr(ig, "_fetch_with_selenium", lambda u, d=False: None)
    result = ig.get_followers("https://www.instagram.com/alice/", max_retries=3, retry_delay=9)
    assert result == {"username": "alice", "followers": None}
    assert len(attempts) == 3
    assert no_sleep == [9, 9]  # no sleep after the final attempt


def test_get_followers_empty_username_makes_no_requests(
    monkeypatch: pytest.MonkeyPatch, no_sleep
) -> None:
    monkeypatch.setattr(ig, "_fetch_with_api", lambda *a: pytest.fail("no fetch expected"))
    assert ig.get_followers("https://www.instagram.com/") == {"username": "", "followers": None}
