"""Tests for utils.py: price parsing, URL handling and data models."""

import asyncio

import pytest
import requests

import utils
from utils import (
    FetcherStats,
    ProductResult,
    ScraperStats,
    expand_short_url,
    extract_asin,
    extract_domain,
    is_short_url,
    normalize_url,
    parse_price_flexible,
    parse_price_from_parts,
    parse_price_text,
    process_amazon_url,
    safe_close,
)

ASIN = "B0ABCDEFGH"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("44,95€", 44.95),
        ("$19.99", 19.99),
        ("€ 29,99", 29.99),
        ("1.234,56 €", 1234.56),
        ("1,234.56", 1234.56),
        ("£1,299.00", 1299.0),
        ("¥1,234", 1234.0),
        ("1.234", 1234.0),
        ("0,99", 0.99),
        ("1 234,56 €", 1234.56),
        ("1 234,56 €", 1234.56),
        ("EUR 29.99", 29.99),
        ("R$ 1.234,56", 1234.56),
        ("29,99 - 39,99", 29.99),
    ],
)
def test_parse_price_text_formats(text, expected):
    """Common European and US price strings parse to the right float."""
    assert parse_price_text(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text", [None, "", "   ", "free", "N/A", "0,00", "9999999,00", 12345]
)
def test_parse_price_text_rejects_invalid(text):
    """Empty, non-numeric, non-string and out-of-range values yield None."""
    assert parse_price_text(text) is None


def test_parse_price_text_rejects_non_ascii_digits():
    """Unicode digits are not accepted as a price."""
    assert parse_price_text("٣٤,٩٥") is None


def test_parse_price_from_parts():
    """Whole and fraction parts are joined, ignoring thousands separators."""
    assert parse_price_from_parts("44,", "95") == pytest.approx(44.95)
    assert parse_price_from_parts("1.234,", "50") == pytest.approx(1234.5)


@pytest.mark.parametrize(
    "whole, fraction", [("", "95"), ("44", ""), (None, "95"), ("ab", "cd"), ("0", "00")]
)
def test_parse_price_from_parts_rejects_invalid(whole, fraction):
    """Missing, non-numeric or out-of-range parts yield None."""
    assert parse_price_from_parts(whole, fraction) is None


def test_parse_price_flexible_dispatch():
    """Text wins over parts; parts are used when text is absent."""
    assert parse_price_flexible(text="$5.00", whole="9", fraction="99") == 5.0
    assert parse_price_flexible(whole="9", fraction="99") == pytest.approx(9.99)
    assert parse_price_flexible() is None


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.amazon.it/dp/{ASIN}",
        f"https://www.amazon.it/dp/{ASIN}/ref=sr_1_1",
        f"https://www.amazon.it/Some-Product-Name/dp/{ASIN}?th=1",
        f"https://www.amazon.it/dp/{ASIN}#reviews",
        f"https://www.amazon.it/gp/product/{ASIN}",
        f"https://www.amazon.it/gp/aw/d/{ASIN}/",
        f"https://www.amazon.it/x?foo=1&ASIN={ASIN}",
    ],
)
def test_extract_asin_patterns(url):
    """Every supported URL shape yields the ASIN."""
    assert extract_asin(url) == ASIN


@pytest.mark.parametrize(
    "url",
    ["https://www.amazon.it/", f"https://www.amazon.it/dp/{ASIN}EXTRA", "dp/short"],
)
def test_extract_asin_none(url):
    """URLs without a well-formed ASIN return None."""
    assert extract_asin(url) is None


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://amzn.eu/d/abc123", True),
        ("amzn.to/3xyz", True),
        ("https://www.amzn.com/dp/B0ABCDEFGH", True),
        ("https://a.co/d/abc", True),
        ("https://www.amazon.it/dp/B0ABCDEFGH", False),
        ("https://www.amazon.com/dp/B0ABCDEFGH?tag=a.com", False),
        ("https://www.amazon.co.uk/dp/B0ABCDEFGH", False),
        ("https://example.com/redirect/amzn.eu", False),
    ],
)
def test_is_short_url(url, expected):
    """Short-URL detection looks at the host only."""
    assert is_short_url(url) is expected


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.amazon.it/dp/X", "amazon.it"),
        ("https://www.amazon.co.uk/dp/X", "amazon.co.uk"),
        ("https://www.amazon.com.au/dp/X", "amazon.com.au"),
        ("https://www.amazon.com/dp/X", "amazon.com"),
        ("https://WWW.AMAZON.DE/dp/X", "amazon.de"),
        ("amazon.fr/dp/X", "amazon.fr"),
        ("https://evil.example/?u=amazon.it/dp/X", None),
        ("https://notamazon.it/dp/X", None),
        ("", None),
    ],
)
def test_extract_domain(url, expected):
    """The Amazon domain is taken from the host, never from the path or query."""
    assert extract_domain(url) == expected


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://x.it", "https://x.it"),
        ("amzn.eu/d/abc", "https://amzn.eu/d/abc"),
        ("amazon.it/dp/X", "https://www.amazon.it/dp/X"),
        ("www.amazon.it/dp/X", "https://www.amazon.it/dp/X"),
        ("example.com", None),
    ],
)
def test_normalize_url(url, expected):
    """A missing scheme is added; unknown hosts are not normalized."""
    assert normalize_url(url) == expected


class _FakeResponse:
    """Minimal requests.Response stand-in usable as a context manager."""

    def __init__(self, url):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_expand_short_url_follows_redirect(monkeypatch):
    """The final redirect URL is returned and the config timeout is used."""
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return _FakeResponse(f"https://www.amazon.it/dp/{ASIN}")

    monkeypatch.setattr(utils.requests, "get", fake_get)
    monkeypatch.setattr(utils.config, "SHORT_URL_EXPANSION_TIMEOUT", 7)

    assert expand_short_url("amzn.eu/d/abc") == f"https://www.amazon.it/dp/{ASIN}"
    assert seen["url"] == "https://amzn.eu/d/abc"
    assert seen["timeout"] == 7


def test_expand_short_url_non_short_is_none():
    """A regular Amazon URL is never fetched."""
    assert expand_short_url(f"https://www.amazon.it/dp/{ASIN}") is None


def test_expand_short_url_network_error(monkeypatch):
    """Request failures are swallowed and reported as None."""

    def fail(url, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(utils.requests, "get", fail)
    assert expand_short_url("https://amzn.eu/d/abc") is None


def test_process_amazon_url_cleans_long_url():
    """Tracking noise is dropped and the canonical form is returned."""
    url = f"https://www.amazon.it/Some-Name/dp/{ASIN}/ref=sr_1_1?keywords=x"
    assert process_amazon_url(url) == f"https://amazon.it/dp/{ASIN}"


def test_process_amazon_url_expands_short(monkeypatch):
    """Short URLs are expanded before the ASIN is extracted."""
    monkeypatch.setattr(
        utils, "expand_short_url", lambda url: f"https://www.amazon.de/dp/{ASIN}?x=1"
    )
    assert process_amazon_url("https://amzn.eu/d/abc") == f"https://amazon.de/dp/{ASIN}"


def test_process_amazon_url_failed_expansion(monkeypatch):
    """A failed expansion invalidates the URL."""
    monkeypatch.setattr(utils, "expand_short_url", lambda url: None)
    assert process_amazon_url("https://amzn.eu/d/abc") is None


@pytest.mark.parametrize(
    "url",
    ["https://www.amazon.it/", "https://example.com/dp/B0ABCDEFGH", "not a url"],
)
def test_process_amazon_url_invalid(url):
    """Missing ASIN or non-Amazon host is rejected."""
    assert process_amazon_url(url) is None


def test_product_result_success_flag():
    """A result is successful only with URL, price and name."""
    assert ProductResult("o", "c", 1.0, "n", None).is_successful
    assert not ProductResult("o", "c", None, "n", None).is_successful
    assert not ProductResult("o", None, 1.0, "n", None).is_successful


def test_stats_calculations():
    """Success rate and duration handle empty and populated stats."""
    assert FetcherStats(name="x").success_rate == 0.0
    assert FetcherStats(name="x", attempts=4, successes=1).success_rate == 25.0

    stats = ScraperStats()
    assert stats.duration == 0.0
    stats.start_time, stats.end_time = 10.0, 25.0
    assert stats.duration == 15.0
    stats.add_fetcher("api", "PA-API")
    assert stats.fetchers["api"].name == "PA-API"


def test_safe_close_swallows_errors():
    """Cleanup failures are logged, not raised; None resources are ignored."""

    class Broken:
        async def close(self):
            raise RuntimeError("boom")

    asyncio.run(safe_close(Broken(), "broken"))
    asyncio.run(safe_close(None, "none"))
