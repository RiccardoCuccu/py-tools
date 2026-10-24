"""Tests for main.py: orchestration, input parsing and output writing with fake fetchers."""

import asyncio

import pytest

import config
import image_downloader
import main
from main import AmazonScraper
from utils import BaseFetcher

ASIN_A = "B0AAAAAAAA"
ASIN_B = "B0BBBBBBBB"
URL_A = f"https://www.amazon.it/dp/{ASIN_A}"
URL_B = f"https://www.amazon.it/dp/{ASIN_B}"


class FakeFetcher(BaseFetcher):
    """Fetcher returning canned data keyed by URL substring."""

    def __init__(self, key="html", data=None, batch=None):
        self._key = key
        self.data = data or {}
        self.batch = batch
        self.fetch_calls = []

    @property
    def name(self):
        return f"fake-{self._key}"

    @property
    def stats_key(self):
        return self._key

    async def fetch(self, url):
        self.fetch_calls.append(url)
        for fragment, value in self.data.items():
            if fragment in url:
                return value
        return None

    async def fetch_batch(self, urls):
        if self.batch is None:
            return await super().fetch_batch(urls)
        return {url: self.batch.get(url) for url in urls}


GOOD = {"price": 10.5, "name": "Thing", "image_url": None}


@pytest.fixture(autouse=True)
def fast_config(monkeypatch, tmp_path):
    """Remove all pacing delays and keep images and logs inside tmp_path."""
    monkeypatch.setattr(config, "REQUEST_DELAY", 0)
    monkeypatch.setattr(config, "RETRY_DELAY_MIN", 0)
    monkeypatch.setattr(config, "RETRY_DELAY_MAX", 0)
    monkeypatch.setattr(config, "MAX_HTTP_RETRIES", 2)
    monkeypatch.setattr(config, "ENABLE_IMAGE_DOWNLOAD", False)
    monkeypatch.setattr(config, "IMAGES_OUTPUT_DIR", str(tmp_path / "images"))
    monkeypatch.setattr(config, "LOG_FILE", str(tmp_path / "scraper.log"))


def _scraper(monkeypatch, fetchers):
    """Build a scraper whose fetchers are the given instances, in order."""
    classes = {
        f.stats_key: ((lambda f=f: f), f.stats_key, f.name) for f in fetchers
    }
    monkeypatch.setattr(main, "load_fetcher_classes", lambda: classes)
    monkeypatch.setattr(config, "FETCHER_ORDER", [f.stats_key for f in fetchers])
    return AmazonScraper()


def _run_file(scraper, tmp_path, lines):
    input_file = tmp_path / "in.txt"
    input_file.write_text("\n".join(lines), encoding="utf-8")
    output_file = tmp_path / "out.txt"
    found = asyncio.run(scraper.process_file(str(input_file), str(output_file)))
    return found, output_file.read_text(encoding="utf-8")


def test_sequential_output_format(monkeypatch, tmp_path):
    """Successes, partial results, failures and bad lines are written correctly."""
    fetcher = FakeFetcher("html", {ASIN_A: GOOD, ASIN_B: {"price": None, "name": "x", "image_url": None}})
    scraper = _scraper(monkeypatch, [fetcher])
    found, text = _run_file(scraper, tmp_path, [
        "# comment", "", URL_A, URL_B, "https://example.com/x", "amazon.it/nothing",
    ])

    assert found is True
    assert f"https://amazon.it/dp/{ASIN_A} | {config.CURRENCY_SYMBOL}10.50 | Thing" in text
    assert f"https://amazon.it/dp/{ASIN_B} | N/A | N/A" in text
    assert "# FAILED: amazon.it/nothing" in text
    assert "example.com" not in text
    assert scraper.stats.successful == 1
    assert scraper.stats.failed == 2


def test_missing_input_file_reports_failure(monkeypatch, tmp_path):
    """A missing input file returns False and writes nothing."""
    scraper = _scraper(monkeypatch, [FakeFetcher()])
    output = tmp_path / "out.txt"
    assert asyncio.run(scraper.process_file(str(tmp_path / "nope.txt"), str(output))) is False
    assert not output.exists()


def test_empty_input_does_not_crash(monkeypatch, tmp_path, capsys):
    """An input without URLs produces a header-only output and a summary."""
    scraper = _scraper(monkeypatch, [FakeFetcher()])
    found, text = _run_file(scraper, tmp_path, ["# nothing here"])
    assert found is True
    assert text.startswith("# Amazon Product Data Export")
    assert "SCRAPING SUMMARY" in capsys.readouterr().out


def test_fallback_to_next_fetcher_and_stats(monkeypatch):
    """When the first fetcher fails the next one is used and stats track both."""
    first = FakeFetcher("api")
    second = FakeFetcher("html", {ASIN_A: GOOD})
    scraper = _scraper(monkeypatch, [first, second])
    data = asyncio.run(scraper.fetch_product_data(URL_A))

    assert data == GOOD
    assert scraper.stats.fetchers["api"].failures == 1
    assert scraper.stats.fetchers["html"].successes == 1


def test_retry_exhaustion_returns_none(monkeypatch):
    """All retries are attempted before giving up."""
    fetcher = FakeFetcher("html")
    scraper = _scraper(monkeypatch, [fetcher])
    assert asyncio.run(scraper.fetch_product_data_with_retry(URL_A)) is None
    assert len(fetcher.fetch_calls) == config.MAX_HTTP_RETRIES


def test_fetcher_exception_is_contained(monkeypatch):
    """A crashing fetcher is recorded and the next fetcher still runs."""

    class Crashing(FakeFetcher):
        async def fetch(self, url):
            raise RuntimeError("kaboom")

    scraper = _scraper(monkeypatch, [Crashing("api"), FakeFetcher("html", {ASIN_A: GOOD})])
    assert asyncio.run(scraper.fetch_product_data(URL_A)) == GOOD
    assert scraper.stats.fetchers["api"].last_error == "kaboom"


def test_exclude_skips_fetcher(monkeypatch):
    """Excluded stats keys are not called and not counted."""
    api = FakeFetcher("api", {ASIN_A: GOOD})
    html = FakeFetcher("html", {ASIN_A: GOOD})
    scraper = _scraper(monkeypatch, [api, html])
    asyncio.run(scraper.fetch_product_data(URL_A, frozenset({"api"})))
    assert api.fetch_calls == []
    assert scraper.stats.fetchers["api"].attempts == 0


def test_batch_complete_data_is_used_and_incomplete_falls_back(monkeypatch, tmp_path):
    """Complete batch data is final; incomplete data goes to the other fetchers only."""
    clean_a, clean_b = f"https://amazon.it/dp/{ASIN_A}", f"https://amazon.it/dp/{ASIN_B}"
    api = FakeFetcher(
        "api",
        data={ASIN_B: GOOD},  # must never be used: the batch call already tried PA-API
        batch={URL_A: GOOD, URL_B: {"price": None, "name": "partial", "image_url": None}},
    )
    html = FakeFetcher("html", {ASIN_B: {"price": 3.0, "name": "From HTML", "image_url": None}})
    scraper = _scraper(monkeypatch, [api, html])
    monkeypatch.setattr(config, "ENABLE_API_BATCH_REQUESTS", True)

    found, text = _run_file(scraper, tmp_path, [URL_A, URL_B])

    assert found is True
    assert f"{clean_a} | {config.CURRENCY_SYMBOL}10.50 | Thing" in text
    assert f"{clean_b} | {config.CURRENCY_SYMBOL}3.00 | From HTML" in text
    assert api.fetch_calls == []
    assert scraper.stats.fetchers["api"].attempts == 2
    assert scraper.stats.successful == 2


def test_images_downloaded_to_configured_dir(monkeypatch, tmp_path):
    """Images of successful products are saved by ASIN under the configured dir."""
    monkeypatch.setattr(config, "ENABLE_IMAGE_DOWNLOAD", True)
    saved = []

    async def fake_download(self, url, asin, max_retries=None):
        saved.append((url, asin, self.output_dir))
        return str(self.output_dir / f"{asin}.jpg")

    monkeypatch.setattr(image_downloader.ImageDownloader, "download_image", fake_download)
    data = {"price": 1.0, "name": "n", "image_url": "https://img/a.jpg"}
    scraper = _scraper(monkeypatch, [FakeFetcher("html", {ASIN_A: data})])
    _run_file(scraper, tmp_path, [URL_A])

    assert saved == [("https://img/a.jpg", ASIN_A, tmp_path / "images")]


def test_no_fetchers_exits(monkeypatch):
    """Without any usable fetcher the scraper exits with an error."""
    monkeypatch.setattr(main, "load_fetcher_classes", lambda: {})
    with pytest.raises(SystemExit) as exc:
        AmazonScraper()
    assert exc.value.code == 1


def test_failing_fetcher_init_is_skipped(monkeypatch):
    """A fetcher whose constructor raises is dropped, others remain."""

    def broken():
        raise ValueError("no credentials")

    ok = FakeFetcher("html")
    monkeypatch.setattr(main, "load_fetcher_classes", lambda: {
        "api": (broken, "api", "PA-API"),
        "html": ((lambda: ok), "html", "HTML"),
    })
    monkeypatch.setattr(config, "FETCHER_ORDER", ["api", "html"])
    scraper = AmazonScraper()
    assert scraper.fetchers == [ok]


def test_load_fetcher_classes_respects_flags(monkeypatch):
    """Only enabled fetchers are loaded (and imported)."""
    monkeypatch.setattr(config, "ENABLE_FETCHER_API", False)
    monkeypatch.setattr(config, "ENABLE_FETCHER_BROWSER", False)
    assert set(main.load_fetcher_classes()) == {"html"}
