"""Tests for fetcher_html.py: HTML parsing and HTTP handling with a fake session."""

import asyncio

import pytest
from bs4 import BeautifulSoup

import config
import fetcher_html
from fetcher_html import HTMLFetcher, HTTPSessionManager

ASIN = "B0ABCDEFGH"
URL = f"https://amazon.it/dp/{ASIN}"


def _page(price_html, asin_attr=ASIN, title="  Nice Gadget  ", image=""):
    """Build a minimal product page."""
    attr = f' data-csa-c-asin="{asin_attr}"' if asin_attr else ""
    title_html = f'<span id="productTitle">{title}</span>' if title else ""
    return (
        "<html><body>"
        f"{title_html}{image}"
        f'<div id="corePrice_feature_div"{attr}>{price_html}</div>'
        "</body></html>"
    )


OFFSCREEN = '<span class="a-price"><span class="a-offscreen">29,99&nbsp;&euro;</span></span>'
PARTS = (
    '<span class="a-price"><span class="a-price-whole">1.234'
    '<span class="a-price-decimal">,</span></span>'
    '<span class="a-price-fraction">50</span></span>'
)


def _soup(html):
    return BeautifulSoup(html, "lxml")


@pytest.fixture
def fetcher():
    return HTMLFetcher()


def test_extract_price_offscreen(fetcher):
    """The offscreen span is the primary price source."""
    assert fetcher._extract_price(_soup(_page(OFFSCREEN)), ASIN) == pytest.approx(29.99)


def test_extract_price_from_parts(fetcher):
    """Whole and fraction spans are used when no offscreen text exists."""
    assert fetcher._extract_price(_soup(_page(PARTS)), ASIN) == pytest.approx(1234.5)


def test_extract_price_asin_mismatch(fetcher):
    """A price block that belongs to another ASIN is ignored."""
    soup = _soup(_page(OFFSCREEN, asin_attr="B0ZZZZZZZZ"))
    assert fetcher._extract_price(soup, ASIN) is None


def test_extract_price_missing_blocks(fetcher):
    """Pages without the price container return None."""
    assert fetcher._extract_price(_soup("<html></html>"), ASIN) is None
    assert fetcher._extract_price(_soup(_page("<p>no price</p>")), ASIN) is None


def test_extract_product_name(fetcher):
    """The product title is stripped; absence gives None."""
    assert fetcher._extract_product_name(_soup(_page(OFFSCREEN))) == "Nice Gadget"
    assert fetcher._extract_product_name(_soup(_page(OFFSCREEN, title=""))) is None


def test_extract_image_prefers_hires_and_skips_non_http(fetcher):
    """data-old-hires beats src; non-http sources are skipped."""
    good = '<img id="landingImage" data-old-hires="https://x/hi.jpg" src="https://x/lo.jpg">'
    assert fetcher._extract_product_image(_soup(_page(OFFSCREEN, image=good))) == "https://x/hi.jpg"

    data_uri = '<img id="landingImage" data-old-hires="" src="data:image/gif;base64,AAAA">'
    assert fetcher._extract_product_image(_soup(_page(OFFSCREEN, image=data_uri))) is None


@pytest.mark.parametrize(
    "body",
    [
        "<html>Robot Check</html>",
        "<html>Enter the characters you see below</html>",
        '<form action="/errors/validateCaptcha"></form>',
        '<img src="https://x/captcha.jpg">',
    ],
)
def test_captcha_detection(fetcher, body):
    """Known bot-check markers are recognised."""
    assert fetcher._is_captcha_page(_soup(body))


def test_not_captcha(fetcher):
    """A normal product page is not flagged."""
    assert not fetcher._is_captcha_page(_soup(_page(OFFSCREEN)))


def test_headers_avoid_brotli(fetcher):
    """Brotli is not advertised because aiohttp may lack a decoder for it."""
    headers = fetcher._get_random_headers()
    assert "br" not in headers["Accept-Encoding"]
    assert headers["User-Agent"] in config.USER_AGENTS


class _FakeResponse:
    def __init__(self, text, status=200):
        self._text = text
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        return self.response


def _use_session(monkeypatch, response):
    session = _FakeSession(response)

    async def get_session():
        return session

    monkeypatch.setattr(HTTPSessionManager, "get_session", get_session)
    return session


def test_fetch_success(fetcher, monkeypatch):
    """A product page yields price, name and image."""
    image = '<img id="landingImage" src="https://x/a.jpg">'
    session = _use_session(monkeypatch, _FakeResponse(_page(OFFSCREEN, image=image)))
    data = asyncio.run(fetcher.fetch(URL))
    assert data == {"price": pytest.approx(29.99), "name": "Nice Gadget", "image_url": "https://x/a.jpg"}
    assert session.requested == [URL]


def test_fetch_captcha_returns_none(fetcher, monkeypatch):
    """A CAPTCHA page is treated as a failed fetch."""
    _use_session(monkeypatch, _FakeResponse("<html>Robot Check</html>"))
    assert asyncio.run(fetcher.fetch(URL)) is None


def test_fetch_http_error_returns_none(fetcher, monkeypatch):
    """HTTP errors are logged and reported as None."""
    _use_session(monkeypatch, _FakeResponse("", status=503))
    assert asyncio.run(fetcher.fetch(URL)) is None


def test_session_uses_configured_pool_limits(monkeypatch):
    """The shared session honours the pool settings from config."""
    monkeypatch.setattr(HTTPSessionManager, "_instance", None)
    monkeypatch.setattr(config, "HTML_CONNECTION_POOL_LIMIT", 7)
    monkeypatch.setattr(config, "HTML_CONNECTION_POOL_LIMIT_PER_HOST", 3)

    async def run():
        session = await HTTPSessionManager.get_session()
        try:
            connector = session.connector
            assert connector is not None
            return connector.limit, connector.limit_per_host
        finally:
            await session.close()

    assert asyncio.run(run()) == (7, 3)
    monkeypatch.setattr(fetcher_html.HTTPSessionManager, "_instance", None)
