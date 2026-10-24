"""Tests for webpage_carbon_dating: date normalisation, metadata extraction, URL handling,
and the fetch wrapper's error paths (all HTTP calls are mocked).
"""

from __future__ import annotations

import pytest
import requests

import webpage_carbon_dating as wcd


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, content: bytes = b"", status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2021-03-05T10:00:00Z", "2021-03-05"),
        ("2021-03-05 10:00:00", "2021-03-05"),
        ("  2021-03-05  ", "2021-03-05"),
        ("2021-03-05", "2021-03-05"),
        ("March 5, 2021", "March 5, 2021"),
    ],
)
def test_normalize_date(raw: str, expected: str) -> None:
    assert wcd.normalize_date(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("example.com/post", "https://example.com/post"),
        ("  https://example.com ", "https://example.com"),
        ("http://example.com", "http://example.com"),
        ("   ", ""),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert wcd.normalize_url(raw) == expected


@pytest.mark.parametrize(
    "tag",
    [
        '<meta property="article:published_time" content="2020-01-02T03:04:05Z">',
        '<meta name="date" content="2020-01-02">',
        '<meta name="pubdate" content="2020-01-02 03:04">',
        '<meta name="article:published_time" content="2020-01-02T00:00:00+01:00">',
        '<meta name="DC.date.issued" content="2020-01-02">',
        '<meta itemprop="datePublished" content="2020-01-02T10:00">',
        '<meta property="og:published_time" content="2020-01-02T10:00">',
    ],
)
def test_extract_from_each_supported_meta_tag(tag: str) -> None:
    html = f"<html><head>{tag}</head><body></body></html>"
    assert wcd.extract_publication_date(html) == "2020-01-02"


def test_extract_falls_back_to_time_element() -> None:
    html = '<body><time datetime="2019-07-08T09:10:11Z">July 8</time></body>'
    assert wcd.extract_publication_date(html) == "2019-07-08"


def test_extract_skips_empty_meta_and_uses_next_candidate() -> None:
    html = (
        '<meta property="article:published_time" content="">'
        '<meta name="date" content="2018-05-06">'
    )
    assert wcd.extract_publication_date(html) == "2018-05-06"


def test_extract_skips_empty_time_and_uses_later_one() -> None:
    html = '<time datetime=""></time><time datetime="2017-01-02">x</time>'
    assert wcd.extract_publication_date(html) == "2017-01-02"


def test_extract_meta_takes_priority_over_time() -> None:
    html = '<time datetime="2000-01-01"></time><meta name="date" content="2010-02-03">'
    assert wcd.extract_publication_date(html) == "2010-02-03"


def test_extract_returns_none_when_missing() -> None:
    assert wcd.extract_publication_date("<html><body>nothing</body></html>") is None
    assert wcd.extract_publication_date(b"") is None


def test_extract_accepts_bytes() -> None:
    html = '<meta name="date" content="2020-02-02">'.encode("utf-8")
    assert wcd.extract_publication_date(html) == "2020-02-02"


def test_get_publication_date_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_get(url, headers, timeout):
        seen.update(url=url, headers=headers, timeout=timeout)
        return FakeResponse(b'<meta name="date" content="2020-04-05T00:00:00Z">')

    monkeypatch.setattr(wcd.requests, "get", fake_get)
    result = wcd.get_publication_date_from_html("example.com/a")

    assert result == "Publication date found: 2020-04-05"
    assert seen["url"] == "https://example.com/a"
    assert seen["timeout"] == wcd.REQUEST_TIMEOUT_SECONDS
    assert "User-Agent" in seen["headers"]


def test_get_publication_date_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wcd.requests, "get", lambda *a, **k: FakeResponse(b"<html></html>"))
    assert (
        wcd.get_publication_date_from_html("https://example.com")
        == "Publication date not found in the metadata."
    )


def test_get_publication_date_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wcd.requests, "get", lambda *a, **k: FakeResponse(b"", 404))
    assert wcd.get_publication_date_from_html("https://example.com") == (
        "Error loading the page: 404"
    )


def test_get_publication_date_network_error_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args, **kwargs):
        raise requests.ConnectionError("dns failure")

    monkeypatch.setattr(wcd.requests, "get", boom)
    result = wcd.get_publication_date_from_html("https://example.com")
    assert result.startswith("Error loading the page:")
    assert "dns failure" in result


def test_get_publication_date_empty_url_makes_no_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("no request expected")

    monkeypatch.setattr(wcd.requests, "get", fail)
    assert wcd.get_publication_date_from_html("   ") == "Error: no URL provided."
