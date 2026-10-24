"""Tests for fetcher_api.py with a fake PA-API SDK client."""

import asyncio
from typing import Optional
from types import SimpleNamespace

import pytest

import config
import fetcher_api
from fetcher_api import APIFetcher

ASIN_A = "B0AAAAAAAA"
ASIN_B = "B0BBBBBBBB"


def _item(asin, name="Product", amount: Optional[float] = 19.99, display="19,99 EUR", image="https://img/x.jpg"):
    """Build an object shaped like an SDK Item."""
    price = SimpleNamespace(amount=amount, display_amount=display)
    return SimpleNamespace(
        asin=asin,
        item_info=SimpleNamespace(title=SimpleNamespace(display_value=name)),
        offers=SimpleNamespace(listings=[SimpleNamespace(price=price)]),
        images=SimpleNamespace(primary=SimpleNamespace(
            large=SimpleNamespace(url=image), medium=None)),
    )


class FakeApi:
    """Records get_items calls and returns canned items."""

    def __init__(self, items=None, error=None):
        self.items = items or []
        self.error = error
        self.calls = []

    def get_items(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.items


@pytest.fixture
def fetcher(monkeypatch):
    """APIFetcher with the SDK constructor replaced by a recording fake."""
    created = {}

    class FakeAmazonApi:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(fetcher_api, "PAAPI_AVAILABLE", True)
    monkeypatch.setattr(fetcher_api, "AmazonApi", FakeAmazonApi)
    monkeypatch.setattr(fetcher_api, "Country", SimpleNamespace(IT="IT", US="US"))
    instance = APIFetcher()
    setattr(instance, "created_kwargs", created)
    return instance


def test_init_passes_credentials_and_partner_tag(fetcher):
    """The SDK client receives keys, partner tag and throttling from config."""
    assert getattr(fetcher, "created_kwargs")["key"] == "test-access-key"
    assert getattr(fetcher, "created_kwargs")["secret"] == "test-secret-key"
    assert getattr(fetcher, "created_kwargs")["tag"] == "test-tag-21"
    assert getattr(fetcher, "created_kwargs")["throttling"] == config.PA_API_THROTTLING


def test_init_requires_credentials(fetcher, monkeypatch):
    """Missing credentials abort construction."""
    monkeypatch.setattr(config, "PA_API_SECRET_KEY", None)
    with pytest.raises(ValueError, match="credentials"):
        APIFetcher()


def test_init_rejects_unsupported_marketplace(fetcher, monkeypatch):
    """Marketplaces outside the supported list are refused."""
    monkeypatch.setattr(config, "TARGET_MARKETPLACE", "BR")
    with pytest.raises(ValueError, match="Unsupported marketplace"):
        APIFetcher()


def test_init_without_sdk(monkeypatch):
    """A missing SDK raises ImportError."""
    monkeypatch.setattr(fetcher_api, "PAAPI_AVAILABLE", False)
    with pytest.raises(ImportError):
        APIFetcher()


def test_fetch_returns_item_data(fetcher):
    """A single fetch maps name, numeric price and image."""
    fetcher.api = FakeApi([_item(ASIN_A)])
    data = asyncio.run(fetcher.fetch(f"https://amazon.it/dp/{ASIN_A}"))
    assert data == {"price": 19.99, "name": "Product", "image_url": "https://img/x.jpg"}
    assert fetcher.api.calls == [((ASIN_A,), {})]


def test_fetch_bad_url_and_empty_result(fetcher):
    """No ASIN or no items yields None without crashing."""
    fetcher.api = FakeApi([])
    assert asyncio.run(fetcher.fetch("https://amazon.it/")) is None
    assert asyncio.run(fetcher.fetch(f"https://amazon.it/dp/{ASIN_A}")) is None


def test_fetch_sdk_error_returns_none(fetcher):
    """SDK exceptions are logged and reported as None."""
    fetcher.api = FakeApi(error=RuntimeError("Forbidden"))
    assert asyncio.run(fetcher.fetch(f"https://amazon.it/dp/{ASIN_A}")) is None


def test_fetch_batch_sends_one_list_argument(fetcher):
    """All ASINs go to the SDK as a single list, not as extra positional arguments."""
    fetcher.api = FakeApi([_item(ASIN_A, "A"), _item(ASIN_B, "B", amount=5.0)])
    urls = [f"https://amazon.it/dp/{ASIN_A}", f"https://amazon.it/dp/{ASIN_B}"]
    result = asyncio.run(fetcher.fetch_batch(urls))

    assert fetcher.api.calls == [(([ASIN_A, ASIN_B],), {})]
    assert result[urls[0]]["name"] == "A"
    assert result[urls[1]]["price"] == 5.0


def test_fetch_batch_partial_and_invalid_urls(fetcher):
    """URLs without an ASIN or without a returned item map to None."""
    fetcher.api = FakeApi([_item(ASIN_A)])
    urls = [f"https://amazon.it/dp/{ASIN_A}", f"https://amazon.it/dp/{ASIN_B}", "bad"]
    result = asyncio.run(fetcher.fetch_batch(urls))
    assert result[urls[0]] is not None
    assert result[urls[1]] is None
    assert "bad" not in result or result["bad"] is None


def test_fetch_batch_error_returns_none_for_all(fetcher):
    """A failing batch call maps every URL to None."""
    fetcher.api = FakeApi(error=RuntimeError("invalid"))
    urls = [f"https://amazon.it/dp/{ASIN_A}"]
    assert asyncio.run(fetcher.fetch_batch(urls)) == {urls[0]: None}


def test_fetch_batch_size_limits(fetcher):
    """Empty and oversized batches are rejected."""
    with pytest.raises(ValueError):
        asyncio.run(fetcher.fetch_batch([]))
    too_many = [f"https://amazon.it/dp/B0{i:08d}" for i in range(11)]
    with pytest.raises(ValueError):
        asyncio.run(fetcher.fetch_batch(too_many))


def test_price_falls_back_to_display_amount(fetcher):
    """Without a usable numeric amount the display text is parsed."""
    item = _item(ASIN_A, amount=None, display="1.299,00 EUR")
    assert fetcher._extract_item_data(item)["price"] == pytest.approx(1299.0)


def test_item_without_offers_or_images(fetcher):
    """Missing offers and images give None fields rather than errors."""
    item = SimpleNamespace(
        asin=ASIN_A,
        item_info=SimpleNamespace(title=SimpleNamespace(display_value="Only name")),
        offers=None,
        images=None,
    )
    assert fetcher._extract_item_data(item) == {
        "price": None,
        "name": "Only name",
        "image_url": None,
    }
