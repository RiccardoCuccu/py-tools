"""Tests for fetcher_browser.py with fake Playwright objects (no browser is launched)."""

import asyncio
from typing import Any

import pytest

import config
from fetcher_browser import BrowserFetcher

ASIN = "B0ABCDEFGH"
URL = f"https://amazon.it/dp/{ASIN}"


class FakeElement:
    """Stands in for a Playwright ElementHandle."""

    def __init__(self, text="", attrs=None, children=None):
        self.text = text
        self.attrs = attrs or {}
        self.children = children or {}

    async def inner_text(self):
        return self.text

    async def get_attribute(self, name):
        return self.attrs.get(name)

    async def query_selector(self, selector):
        return self.children.get(selector)


class FakePage:
    """Stands in for a Playwright Page."""

    def __init__(self, elements=None):
        self.elements = elements or {}
        self.closed = False
        self.visited = []

    async def goto(self, url, **kwargs):
        self.visited.append(url)

    async def query_selector(self, selector):
        return self.elements.get(selector)

    async def wait_for_selector(self, selector, **kwargs):
        return self.elements.get(selector)

    async def wait_for_timeout(self, _ms):
        return None

    async def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, page):
        self.page = page

    async def new_page(self):
        return self.page


def _price_container(offscreen_text, asin=ASIN):
    price = FakeElement(children={"span.a-offscreen": FakeElement(offscreen_text)})
    return FakeElement(
        attrs={"data-csa-c-asin": asin}, children={"span.a-price": price}
    )


def _fetcher_with(page, monkeypatch):
    monkeypatch.setattr(config, "BROWSER_DELIVERY_POSTAL_CODE", None)
    fetcher = BrowserFetcher()
    fetcher._context = FakeContext(page)
    fetcher._initialized = True
    return fetcher


def test_fetch_extracts_everything(monkeypatch):
    """Price, title and image are read from the page and the page is closed."""
    page: Any = FakePage({
        "#corePrice_feature_div": _price_container("29,99 EUR"),
        "span#productTitle": FakeElement("  Gadget  "),
        "img#landingImage": FakeElement(attrs={"src": "https://x/a.jpg"}),
    })
    fetcher = _fetcher_with(page, monkeypatch)
    data = asyncio.run(fetcher.fetch(URL))
    assert data == {"price": pytest.approx(29.99), "name": "Gadget", "image_url": "https://x/a.jpg"}
    assert page.visited == [URL]
    assert page.closed


def test_price_from_hidden_input(monkeypatch):
    """The hidden customerVisiblePrice input takes precedence."""
    selector = 'input[name*="customerVisiblePrice"][name*="amount"]'
    page: Any = FakePage({selector: FakeElement(attrs={"value": "12,50"})})
    fetcher = _fetcher_with(page, monkeypatch)
    assert asyncio.run(fetcher._extract_price(page, ASIN)) == pytest.approx(12.5)


def test_hidden_input_out_of_range_is_ignored(monkeypatch):
    """Values outside the valid price range are rejected."""
    selector = 'input[name*="customerVisiblePrice"][name*="amount"]'
    page: Any = FakePage({selector: FakeElement(attrs={"value": "0"})})
    fetcher = _fetcher_with(page, monkeypatch)
    assert asyncio.run(fetcher._extract_from_hidden_input(page)) is None


def test_asin_mismatch_skips_core_price(monkeypatch):
    """A core price block for another ASIN is not used."""
    page: Any = FakePage({"#corePrice_feature_div": _price_container("9,99", asin="B0ZZZZZZZZ")})
    fetcher = _fetcher_with(page, monkeypatch)
    assert asyncio.run(fetcher._extract_from_visible_elements(page, ASIN)) is None


def test_fetch_failure_still_closes_page(monkeypatch):
    """Navigation errors give None and the page is still closed."""

    class Boom(FakePage):
        async def goto(self, url, **kwargs):
            raise RuntimeError("net::ERR")

    page = Boom()
    fetcher = _fetcher_with(page, monkeypatch)
    assert asyncio.run(fetcher.fetch(URL)) is None
    assert page.closed


class _Closable:
    def __init__(self, fail=False):
        self.fail = fail
        self.closed = False

    async def close(self):
        self.closed = True
        if self.fail:
            raise RuntimeError("close failed")

    async def stop(self):
        self.closed = True


def test_close_releases_everything_even_if_one_step_fails():
    """A failing context close must not leak the browser or the driver."""
    fetcher = BrowserFetcher()
    context, browser, playwright = _Closable(fail=True), _Closable(), _Closable()
    fetcher._context, fetcher._browser, fetcher._playwright = context, browser, playwright
    fetcher._initialized = True

    asyncio.run(fetcher.close())

    assert context.closed and browser.closed and playwright.closed
    assert fetcher._context is None and fetcher._browser is None
    assert fetcher._playwright is None and fetcher._initialized is False


def test_failed_initialization_can_be_retried(monkeypatch):
    """After a failed launch the fetcher holds no dead handles and starts over."""
    attempts = []

    class FakePlaywright:
        class chromium:
            @staticmethod
            async def launch(**kwargs):
                attempts.append(1)
                raise RuntimeError("no browser binary")

        async def stop(self):
            return None

    class Starter:
        async def start(self):
            return FakePlaywright()

    import fetcher_browser

    monkeypatch.setattr(fetcher_browser, "async_playwright", lambda: Starter())
    fetcher = BrowserFetcher()

    for _ in range(2):
        with pytest.raises(RuntimeError):
            asyncio.run(fetcher._ensure_initialized())
    assert len(attempts) == 2
    assert fetcher._initialized is False
    assert fetcher._browser is None
