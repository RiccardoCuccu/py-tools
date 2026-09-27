"""Tests for downloader.ContentDownloader: content download, caching and retry strategies."""

import gzip
from pathlib import Path
from typing import Any, Callable, Optional

import fitz
import pytest
import requests

import downloader
from downloader import ContentDownloader


# --- helpers ---


class FakeResponse:
    """Minimal stand-in for requests.Response used across mocked HTTP calls."""

    def __init__(
        self,
        status_code: int = 200,
        json_data: Any = None,
        text: str = "",
        content: bytes = b"",
        headers: Optional[dict] = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.content = content
        self.headers = headers or {}

    def json(self) -> Any:
        return self._json_data


@pytest.fixture
def dl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., ContentDownloader]:
    """Return a factory building a ContentDownloader whose cache lives under tmp_path."""

    def _make(cache_only: bool = False) -> ContentDownloader:
        doc_path = tmp_path / "doc.txt"
        doc_path.write_text("document content")
        downloader_instance = ContentDownloader(doc_path, cache_only)
        downloader_instance.cache_dir = tmp_path / "cache"
        downloader_instance.cache_dir.mkdir(exist_ok=True)
        downloader_instance.cache_index_file = downloader_instance.cache_dir / "_index.tsv"
        return downloader_instance

    return _make


HTML_PAGE = "<html><body><script>ignored</script><p>Real page content here.</p></body></html>"


# --- get_cached_sources / get_all_cached_sources ---


def test_get_cached_sources_hit_and_miss(dl: Callable[..., ContentDownloader]) -> None:
    """URLs present in the cache are loaded; URLs absent from the cache are skipped."""
    import hashlib

    downloader_instance = dl()
    real_hash = hashlib.md5("http://cached.example/page".encode()).hexdigest()
    downloader_instance._write_cache(real_hash, "cached content " * 30, "http://cached.example/page")

    sources = downloader_instance.get_cached_sources(
        ["http://cached.example/page", "http://missing.example/page"]
    )
    assert len(sources) == 1
    assert sources[0]["url"] == "http://cached.example/page"


def test_get_all_cached_sources_empty_cache_returns_empty(dl: Callable[..., ContentDownloader]) -> None:
    """An empty cache directory yields no sources and does not crash."""
    downloader_instance = dl()
    assert downloader_instance.get_all_cached_sources() == []


def test_get_all_cached_sources_loads_indexed_and_legacy_entries(
    dl: Callable[..., ContentDownloader]
) -> None:
    """Cache-only loads every cached entry: fixes the bug where cache-only found nothing.

    Entries written with a known URL (via the hash index) resolve to their real URL;
    entries present in the cache directory but missing from the index (pre-existing
    cache files written before the index existed) still load, with a placeholder URL.
    """
    downloader_instance = dl()
    downloader_instance._write_cache("hash_with_url", "indexed content " * 30, "http://known.example/a")

    # Simulate a legacy cache file written before the URL index existed.
    legacy_gz = downloader_instance.cache_dir / "legacy_hash.txt.gz"
    with gzip.open(legacy_gz, "wt", encoding="utf-8") as f:
        f.write("legacy content " * 30)

    sources = downloader_instance.get_all_cached_sources()
    urls = {s["url"] for s in sources}
    assert "http://known.example/a" in urls
    assert any(u.startswith("cached://") for u in urls)
    assert len(sources) == 2


def test_get_all_cached_sources_includes_legacy_uncompressed_txt_files(
    dl: Callable[..., ContentDownloader]
) -> None:
    """A pre-existing uncompressed .txt cache file (no index entry) is picked up too."""
    downloader_instance = dl()
    legacy_txt = downloader_instance.cache_dir / "plain_hash.txt"
    legacy_txt.write_text("plain uncompressed cached content " * 10)
    sources = downloader_instance.get_all_cached_sources()
    assert len(sources) == 1
    assert sources[0]["url"] == "cached://plain_hash"


def test_read_cache_index_swallows_corrupt_index_file(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt/unreadable index file returns an empty index instead of raising."""
    downloader_instance = dl()
    downloader_instance.cache_index_file.write_text("h1\thttp://a.example\n")

    def _boom(*a: object, **k: object) -> str:
        raise OSError("simulated read failure")

    monkeypatch.setattr(Path, "read_text", _boom)
    assert downloader_instance._read_cache_index() == {}


def test_get_all_cached_sources_skips_corrupt_gzip_without_crashing(
    dl: Callable[..., ContentDownloader]
) -> None:
    """A corrupted .gz cache file is skipped gracefully instead of raising."""
    downloader_instance = dl()
    corrupt = downloader_instance.cache_dir / "corrupt_hash.txt.gz"
    corrupt.write_bytes(b"not a real gzip stream")
    sources = downloader_instance.get_all_cached_sources()
    assert sources == []


def test_get_all_cached_sources_skips_too_short_content(dl: Callable[..., ContentDownloader]) -> None:
    """Cached content shorter than 200 chars is not returned as a usable source."""
    downloader_instance = dl()
    downloader_instance._write_cache("short_hash", "too short", "http://short.example")
    assert downloader_instance.get_all_cached_sources() == []


# --- cache index helpers ---


def test_write_cache_records_index_entry_once(dl: Callable[..., ContentDownloader]) -> None:
    """Writing the same hash/url pair twice does not duplicate the index entry."""
    downloader_instance = dl()
    downloader_instance._write_cache("h1", "content " * 30, "http://a.example")
    downloader_instance._write_cache("h1", "content again " * 30, "http://a.example")
    index = downloader_instance._read_cache_index()
    assert index == {"h1": "http://a.example"}


def test_write_cache_without_url_leaves_index_untouched(dl: Callable[..., ContentDownloader]) -> None:
    """Writing cache content without a URL does not create an index entry."""
    downloader_instance = dl()
    downloader_instance._write_cache("h_no_url", "content " * 30)
    assert downloader_instance._read_cache_index() == {}


def test_append_cache_index_swallows_write_errors(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure while appending to the index file is swallowed, not raised."""
    downloader_instance = dl()

    def _boom(*a: object, **k: object) -> None:
        raise OSError("simulated disk error")

    monkeypatch.setattr("builtins.open", _boom)
    downloader_instance._append_cache_index("h1", "http://a.example")  # must not raise


# --- download_all_sources ---


def test_download_all_sources_reports_success_and_failure(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful and failed downloads are separated into the two returned lists."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.time, "sleep", lambda *a, **k: None)

    def _fake_download(url: str) -> tuple[Optional[str], Optional[str]]:
        if "good" in url:
            return "good content " * 30, None
        return None, "simulated failure"

    monkeypatch.setattr(downloader_instance, "_download_content", _fake_download)
    sources, failed = downloader_instance.download_all_sources(
        ["http://good.example", "http://bad.example"]
    )
    assert len(sources) == 1
    assert sources[0]["url"] == "http://good.example"
    assert len(failed) == 1
    assert failed[0]["url"] == "http://bad.example"
    assert failed[0]["reason"] == "simulated failure"


def test_download_all_sources_marks_short_content_as_corrupted(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Content that downloads but is too short is reported with a corruption reason."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(downloader_instance, "_download_content", lambda url: ("short", None))
    sources, failed = downloader_instance.download_all_sources(["http://tiny.example"])
    assert sources == []
    assert "corrupted" in failed[0]["reason"] or "too short" in failed[0]["reason"]


# --- _download_content ---


def test_download_content_returns_cache_hit_without_network(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cached URL is served from cache without any HTTP call."""
    downloader_instance = dl()
    url = "http://cached.example/page"
    import hashlib

    url_hash = hashlib.md5(url.encode()).hexdigest()
    downloader_instance._write_cache(url_hash, "cached body " * 30, url)

    def _boom(*a: object, **k: object) -> None:
        raise AssertionError("network should not be called for a cache hit")

    monkeypatch.setattr(downloader.requests, "get", _boom)
    content, error = downloader_instance._download_content(url)
    assert content is not None
    assert error is None


def test_download_content_academic_source_uses_api_method(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An academic-domain URL is resolved via the API method before falling back to scraping."""
    downloader_instance = dl()
    monkeypatch.setattr(
        downloader_instance, "_try_api_methods", lambda url: ("api content " * 30, None)
    )
    content, error = downloader_instance._download_content("https://arxiv.org/abs/1234.5678")
    assert content is not None
    assert error is None


def test_download_content_falls_back_to_scraping_after_all_strategies_fail(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """When every scraping strategy raises, the last error is returned."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.time, "sleep", lambda *a, **k: None)

    def _timeout(*a: object, **k: object) -> None:
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(downloader_instance, "_method_desktop", _timeout)
    monkeypatch.setattr(downloader_instance, "_method_mobile", _timeout)
    monkeypatch.setattr(downloader_instance, "_method_session", _timeout)

    content, error = downloader_instance._download_content("http://example.com/page")
    assert content is None
    assert "Timeout" in error


def test_download_content_succeeds_on_second_strategy(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the first strategy fails but the second succeeds, its content is returned and cached."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.time, "sleep", lambda *a, **k: None)

    def _connection_error(*a: object, **k: object) -> None:
        raise requests.exceptions.ConnectionError()

    monkeypatch.setattr(downloader_instance, "_method_desktop", _connection_error)
    monkeypatch.setattr(downloader_instance, "_method_mobile", lambda url, timeout: "mobile content " * 30)

    content, error = downloader_instance._download_content("http://example.com/other-page")
    assert content is not None
    assert error is None


def test_download_content_reports_generic_request_exception(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generic RequestException (not Timeout/ConnectionError) is reported via its message."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.time, "sleep", lambda *a, **k: None)

    def _boom(*a: object, **k: object) -> None:
        raise requests.exceptions.RequestException("simulated HTTP 403")

    monkeypatch.setattr(downloader_instance, "_method_desktop", _boom)
    monkeypatch.setattr(downloader_instance, "_method_mobile", _boom)
    monkeypatch.setattr(downloader_instance, "_method_session", _boom)

    content, error = downloader_instance._download_content("http://example.com/forbidden-page")
    assert content is None
    assert "simulated HTTP 403" in error


def test_download_content_catches_unexpected_exception(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unexpected (non-requests) exception in a download method is caught and reported."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.time, "sleep", lambda *a, **k: None)

    def _boom(*a: object, **k: object) -> None:
        raise ValueError("simulated unexpected error")

    monkeypatch.setattr(downloader_instance, "_method_desktop", _boom)
    monkeypatch.setattr(downloader_instance, "_method_mobile", _boom)
    monkeypatch.setattr(downloader_instance, "_method_session", _boom)

    content, error = downloader_instance._download_content("http://example.com/weird-page")
    assert content is None
    assert "Unexpected error" in error


# --- _is_academic_source ---


def test_is_academic_source_detects_known_domains(dl: Callable[..., ContentDownloader]) -> None:
    """Known academic domains are recognized as academic sources."""
    downloader_instance = dl()
    assert downloader_instance._is_academic_source("https://arxiv.org/abs/1234.5678") is True
    assert downloader_instance._is_academic_source("https://example.com/page") is False


# --- _try_api_methods ---


def test_try_api_methods_routes_arxiv(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An arxiv.org URL routes to _fetch_arxiv_api."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader_instance, "_fetch_arxiv_api", lambda url: "arxiv content")
    content, error = downloader_instance._try_api_methods("https://arxiv.org/abs/1234.5678")
    assert content == "arxiv content"
    assert error is None


def test_try_api_methods_routes_doi(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A doi.org URL routes to _fetch_via_unpaywall."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader_instance, "_fetch_via_unpaywall", lambda url: "unpaywall content")
    content, error = downloader_instance._try_api_methods("https://doi.org/10.1000/xyz")
    assert content == "unpaywall content"
    assert error is None


def test_try_api_methods_routes_semantic_scholar(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A semanticscholar.org URL routes to _fetch_semantic_scholar."""
    downloader_instance = dl()
    monkeypatch.setattr(
        downloader_instance, "_fetch_semantic_scholar", lambda url: "semantic content"
    )
    content, error = downloader_instance._try_api_methods(
        "https://www.semanticscholar.org/paper/abcdef"
    )
    assert content == "semantic content"
    assert error is None


def test_try_api_methods_no_match_returns_error(dl: Callable[..., ContentDownloader]) -> None:
    """An unrecognized academic domain returns the "no API method" error."""
    downloader_instance = dl()
    content, error = downloader_instance._try_api_methods("https://researchgate.net/publication/1")
    assert content is None
    assert error == "No API method available"


# --- _fetch_arxiv_api ---


ARXIV_ENTRY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>A Paper Title</title>
    <summary>An abstract summary.</summary>
  </entry>
</feed>
"""


def test_fetch_arxiv_api_success(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful arXiv API response yields a title+abstract content string."""
    downloader_instance = dl()
    monkeypatch.setattr(
        downloader.requests,
        "get",
        lambda *a, **k: FakeResponse(200, content=ARXIV_ENTRY_XML.encode("utf-8")),
    )
    content = downloader_instance._fetch_arxiv_api("https://arxiv.org/abs/1234.5678")
    assert content is not None
    assert "A Paper Title" in content
    assert "An abstract summary." in content


def test_fetch_arxiv_api_no_id_match_returns_none(dl: Callable[..., ContentDownloader]) -> None:
    """A URL without a parsable arXiv id returns None."""
    downloader_instance = dl()
    assert downloader_instance._fetch_arxiv_api("https://arxiv.org/abs/not-an-id") is None


def test_fetch_arxiv_api_non_200_returns_none(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-200 arXiv API response returns None."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResponse(500))
    assert downloader_instance._fetch_arxiv_api("https://arxiv.org/abs/1234.5678") is None


def test_fetch_arxiv_api_exception_returns_none(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network error while fetching the arXiv API returns None."""
    downloader_instance = dl()

    def _boom(*a: object, **k: object) -> None:
        raise requests.exceptions.RequestException("simulated error")

    monkeypatch.setattr(downloader.requests, "get", _boom)
    assert downloader_instance._fetch_arxiv_api("https://arxiv.org/abs/1234.5678") is None


# --- _fetch_via_unpaywall ---


def test_fetch_via_unpaywall_pdf_success(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An open-access PDF location is fetched via _download_pdf_as_text."""
    downloader_instance = dl()
    payload = {
        "is_oa": True,
        "best_oa_location": {
            "url_for_pdf": "https://example.com/paper.pdf",
            "url_for_landing_page": "https://example.com/landing",
        },
    }
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResponse(200, json_data=payload))
    monkeypatch.setattr(downloader_instance, "_download_pdf_as_text", lambda url: "pdf text content")
    content = downloader_instance._fetch_via_unpaywall("https://doi.org/10.1000/abc123")
    assert content == "pdf text content"


def test_fetch_via_unpaywall_landing_page_fallback(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the PDF cannot be fetched, the landing page is tried via _method_desktop."""
    downloader_instance = dl()
    payload = {
        "is_oa": True,
        "best_oa_location": {
            "url_for_pdf": "https://example.com/paper.pdf",
            "url_for_landing_page": "https://example.com/landing",
        },
    }
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResponse(200, json_data=payload))
    monkeypatch.setattr(downloader_instance, "_download_pdf_as_text", lambda url: None)
    monkeypatch.setattr(downloader_instance, "_method_desktop", lambda url, timeout: "landing page text")
    content = downloader_instance._fetch_via_unpaywall("https://doi.org/10.1000/abc123")
    assert content == "landing page text"


def test_fetch_via_unpaywall_metadata_fallback(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no open-access location, title/abstract metadata is used as a last resort."""
    downloader_instance = dl()
    payload = {"is_oa": False, "title": "Paper Title", "abstract": "Paper abstract."}
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResponse(200, json_data=payload))
    content = downloader_instance._fetch_via_unpaywall("https://doi.org/10.1000/abc123")
    assert content is not None
    assert "Paper Title" in content
    assert "Paper abstract." in content


def test_fetch_via_unpaywall_no_doi_match_returns_none(dl: Callable[..., ContentDownloader]) -> None:
    """A URL without a parsable DOI returns None."""
    downloader_instance = dl()
    assert downloader_instance._fetch_via_unpaywall("https://doi.org/not-a-doi") is None


def test_fetch_via_unpaywall_non_200_returns_none(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-200 Unpaywall response returns None."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResponse(404))
    assert downloader_instance._fetch_via_unpaywall("https://doi.org/10.1000/abc123") is None


def test_fetch_via_unpaywall_exception_returns_none(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network error while querying Unpaywall returns None."""
    downloader_instance = dl()

    def _boom(*a: object, **k: object) -> None:
        raise requests.exceptions.RequestException("simulated error")

    monkeypatch.setattr(downloader.requests, "get", _boom)
    assert downloader_instance._fetch_via_unpaywall("https://doi.org/10.1000/abc123") is None


def test_fetch_via_unpaywall_uses_configured_contact_email_url_encoded(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Unpaywall request URL carries the configured contact email, URL-encoded."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader, "get_contact_email", lambda: "a b@example.com")
    requested_urls = []

    def _fake_get(url: str, *a: object, **k: object) -> FakeResponse:
        requested_urls.append(url)
        return FakeResponse(200, json_data={"is_oa": False})

    monkeypatch.setattr(downloader.requests, "get", _fake_get)
    downloader_instance._fetch_via_unpaywall("https://doi.org/10.1000/abc123")
    assert requested_urls
    assert "email=a%20b%40example.com" in requested_urls[0]


# --- _fetch_semantic_scholar ---


def test_fetch_semantic_scholar_success(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful Semantic Scholar response yields a title+abstract content string."""
    downloader_instance = dl()
    payload = {"title": "Some Title", "abstract": "Some abstract."}
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResponse(200, json_data=payload))
    content = downloader_instance._fetch_semantic_scholar(
        "https://www.semanticscholar.org/paper/abcdef1234"
    )
    assert content is not None
    assert "Some Title" in content


def test_fetch_semantic_scholar_no_id_match_returns_none(dl: Callable[..., ContentDownloader]) -> None:
    """A URL without a parsable paper id returns None."""
    downloader_instance = dl()
    assert downloader_instance._fetch_semantic_scholar("https://www.semanticscholar.org/paper/") is None


def test_fetch_semantic_scholar_non_200_returns_none(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-200 Semantic Scholar response returns None."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResponse(500))
    assert downloader_instance._fetch_semantic_scholar(
        "https://www.semanticscholar.org/paper/abcdef1234"
    ) is None


def test_fetch_semantic_scholar_exception_returns_none(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network error while querying Semantic Scholar returns None."""
    downloader_instance = dl()

    def _boom(*a: object, **k: object) -> None:
        raise requests.exceptions.RequestException("simulated error")

    monkeypatch.setattr(downloader.requests, "get", _boom)
    assert downloader_instance._fetch_semantic_scholar(
        "https://www.semanticscholar.org/paper/abcdef1234"
    ) is None


# --- _download_pdf_as_text ---


def test_download_pdf_as_text_extracts_real_pdf_content(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine PDF byte stream is parsed with PyMuPDF and its text returned."""
    downloader_instance = dl()
    pdf_doc = fitz.open()
    page = pdf_doc.new_page()
    page.insert_textbox(fitz.Rect(30, 30, 550, 750), "Downloaded PDF content. " * 20)
    pdf_bytes = pdf_doc.tobytes()
    pdf_doc.close()

    response = FakeResponse(200, content=pdf_bytes, headers={"Content-Type": "application/pdf"})
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: response)
    content = downloader_instance._download_pdf_as_text("https://example.com/paper.pdf")
    assert content is not None
    assert "Downloaded PDF content." in content


def test_download_pdf_as_text_non_pdf_content_type_returns_none(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A response that is not actually a PDF (wrong Content-Type) returns None."""
    downloader_instance = dl()
    response = FakeResponse(200, content=b"<html></html>", headers={"Content-Type": "text/html"})
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: response)
    assert downloader_instance._download_pdf_as_text("https://example.com/notapdf") is None


def test_download_pdf_as_text_non_200_returns_none(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-200 response returns None."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResponse(404))
    assert downloader_instance._download_pdf_as_text("https://example.com/missing.pdf") is None


def test_download_pdf_as_text_exception_returns_none(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network error while downloading the PDF returns None."""
    downloader_instance = dl()

    def _boom(*a: object, **k: object) -> None:
        raise requests.exceptions.RequestException("simulated error")

    monkeypatch.setattr(downloader.requests, "get", _boom)
    assert downloader_instance._download_pdf_as_text("https://example.com/paper.pdf") is None


# --- _read_cache / _write_cache ---


def test_write_cache_then_read_cache_roundtrip_gzip(dl: Callable[..., ContentDownloader]) -> None:
    """Content written via _write_cache is readable back via _read_cache (gzip path)."""
    downloader_instance = dl()
    downloader_instance._write_cache("roundtrip_hash", "hello cached world")
    assert downloader_instance._read_cache("roundtrip_hash") == "hello cached world"


def test_read_cache_migrates_legacy_uncompressed_file(dl: Callable[..., ContentDownloader]) -> None:
    """A legacy uncompressed .txt cache file is migrated to .txt.gz and the original removed."""
    downloader_instance = dl()
    legacy_file = downloader_instance.cache_dir / "legacy2_hash.txt"
    legacy_file.write_text("legacy uncompressed content")

    content = downloader_instance._read_cache("legacy2_hash")
    assert content == "legacy uncompressed content"
    assert not legacy_file.exists()
    assert (downloader_instance.cache_dir / "legacy2_hash.txt.gz").exists()


def test_read_cache_missing_returns_none(dl: Callable[..., ContentDownloader]) -> None:
    """A hash with no cache file at all returns None."""
    downloader_instance = dl()
    assert downloader_instance._read_cache("nonexistent_hash") is None


def test_write_cache_falls_back_to_plain_text_on_gzip_failure(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If gzip writing fails, content is written as a plain .txt file instead."""
    downloader_instance = dl()

    def _boom(*a: object, **k: object) -> None:
        raise OSError("simulated gzip failure")

    monkeypatch.setattr(downloader.gzip, "open", _boom)
    downloader_instance._write_cache("fallback_hash", "fallback content")
    assert (downloader_instance.cache_dir / "fallback_hash.txt").read_text() == "fallback content"


# --- _method_desktop / _method_mobile / _method_session ---


def test_method_desktop_success_extracts_text(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 response is parsed into cleaned text."""
    downloader_instance = dl()
    monkeypatch.setattr(
        downloader.requests, "get", lambda *a, **k: FakeResponse(200, content=HTML_PAGE.encode())
    )
    text = downloader_instance._method_desktop("http://example.com", 15)
    assert "Real page content here." in text


def test_method_desktop_non_200_raises(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-200 response raises RequestException."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResponse(404))
    with pytest.raises(requests.exceptions.RequestException):
        downloader_instance._method_desktop("http://example.com", 15)


def test_method_mobile_success_extracts_text(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 response via the mobile User-Agent is parsed into cleaned text."""
    downloader_instance = dl()
    monkeypatch.setattr(
        downloader.requests, "get", lambda *a, **k: FakeResponse(200, content=HTML_PAGE.encode())
    )
    text = downloader_instance._method_mobile("http://example.com", 25)
    assert "Real page content here." in text


def test_method_mobile_non_200_raises(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-200 mobile response raises RequestException."""
    downloader_instance = dl()
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResponse(500))
    with pytest.raises(requests.exceptions.RequestException):
        downloader_instance._method_mobile("http://example.com", 25)


def test_method_session_success_extracts_text(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 response via a fresh session with referrer headers is parsed into cleaned text."""
    downloader_instance = dl()
    monkeypatch.setattr(
        downloader.requests.Session,
        "get",
        lambda self, *a, **k: FakeResponse(200, content=HTML_PAGE.encode()),
    )
    text = downloader_instance._method_session("http://example.com", 35)
    assert "Real page content here." in text


def test_method_session_non_200_raises(
    dl: Callable[..., ContentDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-200 session response raises RequestException."""
    downloader_instance = dl()
    monkeypatch.setattr(
        downloader.requests.Session, "get", lambda self, *a, **k: FakeResponse(503)
    )
    with pytest.raises(requests.exceptions.RequestException):
        downloader_instance._method_session("http://example.com", 35)


# --- _extract_text_from_html ---


def test_extract_text_from_html_strips_scripts_and_normalizes_whitespace(
    dl: Callable[..., ContentDownloader]
) -> None:
    """Script/style/nav/header/footer tags are removed and whitespace is collapsed."""
    downloader_instance = dl()
    html = "<html><body><script>bad()</script><p>Hello   world.</p></body></html>"
    text = downloader_instance._extract_text_from_html(html.encode())
    assert text == "Hello world."


def test_extract_text_from_html_rejects_mostly_non_ascii_content(
    dl: Callable[..., ContentDownloader]
) -> None:
    """Content with a low ASCII ratio (binary/garbled) is rejected as empty."""
    downloader_instance = dl()
    garbled = "<html><body><p>" + ("éèêë" * 100) + "</p></body></html>"
    text = downloader_instance._extract_text_from_html(garbled.encode("utf-8"))
    assert text == ""


# --- _extract_title ---


def test_extract_title_uses_first_sentence(dl: Callable[..., ContentDownloader]) -> None:
    """The first sentence of the content is used as the title when long enough."""
    downloader_instance = dl()
    title = downloader_instance._extract_title("This is a reasonably long first sentence. More text follows.")
    assert title.startswith("This is a reasonably long first sentence")


def test_extract_title_short_sentence_falls_back_to_untitled(dl: Callable[..., ContentDownloader]) -> None:
    """A too-short first sentence falls back to the "Untitled Source" placeholder."""
    downloader_instance = dl()
    assert downloader_instance._extract_title("Hi. More text follows after this short one.") == "Untitled Source"


def test_extract_title_empty_text_falls_back_to_untitled(dl: Callable[..., ContentDownloader]) -> None:
    """Empty content falls back to the "Untitled Source" placeholder."""
    downloader_instance = dl()
    assert downloader_instance._extract_title("") == "Untitled Source"
