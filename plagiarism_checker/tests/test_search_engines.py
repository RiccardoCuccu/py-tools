"""Tests for search_engines.SearchEngineManager: web/academic search and local references."""

from pathlib import Path
from typing import Any, Callable, List, Optional

import keyring
import keyring.errors
import pytest
import requests
from keyring.backends.fail import Keyring as FailKeyring

import search_engines
from search_engines import KEYRING_SERVICE, KEYRING_USERNAME, SearchEngineManager, reset_serpapi_key


# --- helpers ---


class FakeResponse:
    """Minimal stand-in for requests.Response used across mocked HTTP calls."""

    def __init__(
        self,
        status_code: int = 200,
        json_data: Any = None,
        text: str = "",
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.content = content

    def json(self) -> Any:
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., SearchEngineManager]:
    """Return a factory building a SearchEngineManager that never touches the real .serpapi_config."""

    def _make(
        search_engine: str = "auto",
        use_apis: bool = False,
        use_local: bool = False,
        doc_name: str = "doc.txt",
    ) -> SearchEngineManager:
        doc_path = tmp_path / doc_name
        doc_path.write_text("document content")
        with monkeypatch.context() as m:
            m.setattr(SearchEngineManager, "_load_serpapi_key", lambda self: None)
            mgr = SearchEngineManager(search_engine, use_apis, use_local, doc_path)
        mgr.script_dir = tmp_path / "script_dir"
        mgr.script_dir.mkdir(exist_ok=True)
        return mgr

    return _make


# --- _load_serpapi_key ---


def test_load_serpapi_key_env_var_takes_priority(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """SERPAPI_API_KEY, if set, is returned before checking the keyring or any file."""
    monkeypatch.setenv("SERPAPI_API_KEY", "  ENV_KEY  ")
    mgr = manager(search_engine="duckduckgo")
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, "KEYRING_KEY")
    (mgr.script_dir / ".serpapi_config").write_text("FILE_KEY")
    assert mgr._load_serpapi_key() == "ENV_KEY"


def test_load_serpapi_key_reads_from_keyring(
    manager: Callable[..., SearchEngineManager]
) -> None:
    """A key already stored in the OS keyring is returned directly."""
    mgr = manager(search_engine="duckduckgo")
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, "KEYRING_KEY")
    assert mgr._load_serpapi_key() == "KEYRING_KEY"


def test_load_serpapi_key_keyring_get_error_falls_through(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A KeyringError while reading falls through to the next step instead of raising."""
    mgr = manager(search_engine="duckduckgo")

    def _boom(*a: object, **k: object) -> None:
        raise keyring.errors.KeyringError("simulated backend failure")

    monkeypatch.setattr(keyring, "get_password", _boom)
    assert mgr._load_serpapi_key() is None


def test_load_serpapi_key_nothing_configured_non_serpapi_engine_returns_none(
    manager: Callable[..., SearchEngineManager]
) -> None:
    """No env var, no keyring entry, no legacy file, engine != 'serpapi': returns None."""
    mgr = manager(search_engine="auto")
    assert mgr._load_serpapi_key() is None


def test_load_serpapi_key_migration_success_removes_legacy_file(
    manager: Callable[..., SearchEngineManager]
) -> None:
    """A legacy .serpapi_config file is migrated to the keyring and then deleted."""
    mgr = manager(search_engine="duckduckgo")
    (mgr.script_dir / ".serpapi_config").write_text("LEGACY_KEY")

    result = mgr._load_serpapi_key()

    assert result == "LEGACY_KEY"
    assert not (mgr.script_dir / ".serpapi_config").exists()
    assert keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) == "LEGACY_KEY"


def test_load_serpapi_key_migration_empty_file_returns_none(
    manager: Callable[..., SearchEngineManager]
) -> None:
    """An empty legacy .serpapi_config file is treated like a missing key."""
    mgr = manager(search_engine="duckduckgo")
    (mgr.script_dir / ".serpapi_config").write_text("")
    assert mgr._load_serpapi_key() is None


def test_load_serpapi_key_migration_read_exception_returns_none(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If reading the legacy file raises, the method warns and returns None."""
    mgr = manager(search_engine="auto")
    legacy_path = mgr.script_dir / ".serpapi_config"
    legacy_path.write_text("irrelevant")

    real_open = open

    def _boom(path: object, *args: object, **kwargs: object) -> Any:
        if str(path) == str(legacy_path):
            raise OSError("simulated read failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _boom)
    assert mgr._load_serpapi_key() is None


def test_load_serpapi_key_migration_readback_mismatch_keeps_file(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the keyring read-back does not match, the legacy file is kept, not deleted."""
    mgr = manager(search_engine="duckduckgo")
    (mgr.script_dir / ".serpapi_config").write_text("LEGACY_KEY")
    monkeypatch.setattr(keyring, "get_password", lambda *a, **k: None)

    result = mgr._load_serpapi_key()

    assert result == "LEGACY_KEY"
    assert (mgr.script_dir / ".serpapi_config").exists()


def test_load_serpapi_key_migration_set_password_error_keeps_file(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If saving the migrated key to the keyring raises, the legacy file is kept."""
    mgr = manager(search_engine="duckduckgo")
    (mgr.script_dir / ".serpapi_config").write_text("LEGACY_KEY")

    def _boom(*a: object, **k: object) -> None:
        raise keyring.errors.KeyringError("simulated write failure")

    monkeypatch.setattr(keyring, "set_password", _boom)
    result = mgr._load_serpapi_key()

    assert result == "LEGACY_KEY"
    assert (mgr.script_dir / ".serpapi_config").exists()


def test_load_serpapi_key_migration_keyring_unavailable_keeps_file(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no keyring backend available, the legacy key is used but the file is kept."""
    mgr = manager(search_engine="duckduckgo")
    (mgr.script_dir / ".serpapi_config").write_text("LEGACY_KEY")
    monkeypatch.setattr(keyring, "get_keyring", lambda: FailKeyring())

    result = mgr._load_serpapi_key()

    assert result == "LEGACY_KEY"
    assert (mgr.script_dir / ".serpapi_config").exists()


def test_load_serpapi_key_serpapi_engine_prompts_and_saves_to_keyring(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With engine='serpapi' and nothing configured, a confirmed getpass prompt saves to the keyring."""
    import main as main_module

    mgr = manager(search_engine="serpapi")
    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: True)
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "NEWKEY")

    result = mgr._load_serpapi_key()

    assert result == "NEWKEY"
    assert keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) == "NEWKEY"
    assert not (mgr.script_dir / ".serpapi_config").exists()


def test_load_serpapi_key_serpapi_engine_prompt_keyring_unavailable(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no keyring backend, the prompted key is used for the session only, never written to disk."""
    import main as main_module

    mgr = manager(search_engine="serpapi")
    monkeypatch.setattr(keyring, "get_keyring", lambda: FailKeyring())
    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: True)
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "NEWKEY")

    result = mgr._load_serpapi_key()

    assert result == "NEWKEY"
    assert not (mgr.script_dir / ".serpapi_config").exists()


def test_load_serpapi_key_serpapi_engine_prompt_save_failure(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If saving the prompted key to the keyring raises, the key is still returned for this session."""
    import main as main_module

    mgr = manager(search_engine="serpapi")
    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: True)
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "NEWKEY")

    def _boom(*a: object, **k: object) -> None:
        raise keyring.errors.KeyringError("simulated write failure")

    monkeypatch.setattr(keyring, "set_password", _boom)
    result = mgr._load_serpapi_key()

    assert result == "NEWKEY"
    assert not (mgr.script_dir / ".serpapi_config").exists()


def test_load_serpapi_key_empty_input_exits(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty key entered at the prompt exits with code 1."""
    import main as main_module

    mgr = manager(search_engine="serpapi")
    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: True)
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "")

    with pytest.raises(SystemExit) as excinfo:
        mgr._load_serpapi_key()
    assert excinfo.value.code == 1


def test_load_serpapi_key_user_declines_exits(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Declining the prompt when engine='serpapi' exits with code 1."""
    import main as main_module

    mgr = manager(search_engine="serpapi")
    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: False)

    with pytest.raises(SystemExit) as excinfo:
        mgr._load_serpapi_key()
    assert excinfo.value.code == 1


# --- reset_serpapi_key ---


def test_reset_serpapi_key_deletes_stored_key() -> None:
    """A key present in the keyring is deleted and a success message is returned."""
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, "SOME_KEY")
    message = reset_serpapi_key()
    assert "removed" in message.lower()
    assert keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) is None


def test_reset_serpapi_key_no_key_stored() -> None:
    """With no key stored, PasswordDeleteError is handled and a clear message is returned."""
    message = reset_serpapi_key()
    assert "no serpapi key" in message.lower()


def test_reset_serpapi_key_keyring_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no keyring backend available, a clear message is returned without raising."""
    monkeypatch.setattr(keyring, "get_keyring", lambda: FailKeyring())
    message = reset_serpapi_key()
    assert "unavailable" in message.lower()


def test_reset_serpapi_key_generic_keyring_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A generic KeyringError during delete is reported, not raised."""

    def _boom(*a: object, **k: object) -> None:
        raise keyring.errors.KeyringError("simulated backend failure")

    monkeypatch.setattr(keyring, "delete_password", _boom)
    message = reset_serpapi_key()
    assert "could not reset" in message.lower()


# --- search_and_load / local sources ---


def test_search_and_load_skips_local_loading_when_disabled(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """use_local=False never triggers local reference loading."""
    mgr = manager(use_local=False)
    monkeypatch.setattr(mgr, "_search_all_phrases", lambda phrases, max_sources: ["http://a"])
    urls, failed = mgr.search_and_load(["phrase"], 5)
    assert urls == ["http://a"]
    assert failed == []
    assert mgr.local_sources == []


def test_search_and_load_triggers_local_loading_when_enabled(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """use_local=True loads local reference files before searching online."""
    mgr = manager(use_local=True)
    load_calls: List[bool] = []
    monkeypatch.setattr(mgr, "_load_local_sources", lambda: load_calls.append(True))
    monkeypatch.setattr(mgr, "_search_all_phrases", lambda phrases, max_sources: [])
    mgr.search_and_load(["phrase"], 5)
    assert load_calls == [True]


def test_load_local_sources_missing_dir_continues_when_confirmed(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing local_references directory, confirmed to continue, leaves local_sources empty."""
    import main as main_module

    mgr = manager(use_local=True)
    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: True)
    mgr._load_local_sources()
    assert mgr.local_sources == []


def test_load_local_sources_missing_dir_exits_when_declined(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing local_references directory, declined, exits the program."""
    import main as main_module

    mgr = manager(use_local=True)
    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: False)
    with pytest.raises(SystemExit) as excinfo:
        mgr._load_local_sources()
    assert excinfo.value.code == 0


def test_load_local_sources_empty_dir_exits_when_declined(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing but empty local_references directory, declined, exits the program."""
    import main as main_module

    mgr = manager(use_local=True)
    mgr.local_references_dir.mkdir(parents=True)
    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: False)
    with pytest.raises(SystemExit) as excinfo:
        mgr._load_local_sources()
    assert excinfo.value.code == 0


def test_load_local_sources_empty_dir_continues_when_confirmed(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing but empty local_references directory, confirmed, returns without exiting."""
    import main as main_module

    mgr = manager(use_local=True)
    mgr.local_references_dir.mkdir(parents=True)
    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: True)
    mgr._load_local_sources()
    assert mgr.local_sources == []


def test_load_local_sources_loads_valid_files_and_skips_short_ones(
    manager: Callable[..., SearchEngineManager]
) -> None:
    """Reference files with enough content are loaded; too-short content is skipped."""
    mgr = manager(use_local=True)
    mgr.local_references_dir.mkdir(parents=True)
    (mgr.local_references_dir / "good.txt").write_text("x" * 300)
    (mgr.local_references_dir / "short.txt").write_text("tiny")

    mgr._load_local_sources()
    assert len(mgr.local_sources) == 1
    assert mgr.local_sources[0]["file_name"] == "good.txt"
    assert mgr.local_sources[0]["is_local"] is True


# --- _should_include_url ---


def test_should_include_url_excludes_social_domains(
    manager: Callable[..., SearchEngineManager]
) -> None:
    """Social media domains are always excluded regardless of use_apis."""
    mgr = manager(use_apis=False)
    assert mgr._should_include_url("https://www.youtube.com/watch") is False
    assert mgr._should_include_url("https://example.com/page") is True


def test_should_include_url_excludes_api_domains_when_use_apis(
    manager: Callable[..., SearchEngineManager]
) -> None:
    """When use_apis is True, academic API domains are additionally excluded from web results."""
    mgr = manager(use_apis=True)
    assert mgr._should_include_url("https://arxiv.org/abs/1234") is False
    assert mgr._should_include_url("https://example.com/page") is True


# --- _search_all_phrases ---


def test_search_all_phrases_uses_apis_and_web_and_dedupes(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With use_apis=True, results from academic APIs and web search are merged and deduped."""
    mgr = manager(use_apis=True)
    monkeypatch.setattr(search_engines.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(mgr, "_search_academic_apis", lambda q: ["http://dup"])
    monkeypatch.setattr(mgr, "_search_online", lambda q, attempt=0: ["http://dup", "http://web"])
    mgr.serpapi_key = "KEY"

    urls = mgr._search_all_phrases(["phrase one", "phrase two"], max_sources=10)
    assert set(urls) == {"http://dup", "http://web"}


def test_search_all_phrases_limits_to_max_sources(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The number of returned URLs never exceeds max_sources."""
    mgr = manager(use_apis=False, search_engine="duckduckgo")
    monkeypatch.setattr(search_engines.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        mgr, "_search_online", lambda q, attempt=0: [f"http://{q}-{attempt}-a", f"http://{q}-{attempt}-b"]
    )
    urls = mgr._search_all_phrases(["p1", "p2", "p3"], max_sources=2)
    assert len(urls) == 2


def test_search_all_phrases_auto_engine_name_with_and_without_key(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 'auto' engine picks SerpApi when a key is set, DuckDuckGo otherwise (message only)."""
    mgr = manager(search_engine="auto")
    monkeypatch.setattr(search_engines.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(mgr, "_search_online", lambda q, attempt=0: [])
    mgr.serpapi_key = "KEY"
    mgr._search_all_phrases(["only phrase"], max_sources=5)

    mgr.serpapi_key = None
    mgr._search_all_phrases(["only phrase"], max_sources=5)


def test_search_all_phrases_explicit_serpapi_engine_name(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """search_engine='serpapi' selects the "SerpApi" engine label in the status message."""
    mgr = manager(search_engine="serpapi")
    monkeypatch.setattr(search_engines.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(mgr, "_search_online", lambda q, attempt=0: ["http://a"])
    mgr.serpapi_key = "KEY"
    urls = mgr._search_all_phrases(["only phrase"], max_sources=5)
    assert urls == ["http://a"]


def test_search_all_phrases_use_apis_keeps_top_n_when_over_max(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With use_apis=True, more unique sources than max_sources triggers the "kept top N" message."""
    mgr = manager(use_apis=True)
    monkeypatch.setattr(search_engines.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(mgr, "_search_academic_apis", lambda q: ["http://api1", "http://api2"])
    monkeypatch.setattr(mgr, "_search_online", lambda q, attempt=0: ["http://web1", "http://web2"])
    mgr.serpapi_key = "KEY"
    urls = mgr._search_all_phrases(["only phrase"], max_sources=2)
    assert len(urls) == 2


def test_search_all_phrases_use_apis_no_duplicates_no_limiting(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With use_apis=True, unique results under max_sources with no duplicates hit the plain-count branch."""
    mgr = manager(use_apis=True)
    monkeypatch.setattr(search_engines.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(mgr, "_search_academic_apis", lambda q: ["http://api1"])
    monkeypatch.setattr(mgr, "_search_online", lambda q, attempt=0: ["http://web1"])
    mgr.serpapi_key = "KEY"
    urls = mgr._search_all_phrases(["only phrase"], max_sources=10)
    assert set(urls) == {"http://api1", "http://web1"}


def test_search_all_phrases_consecutive_failures_prompt_and_stop(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """3 consecutive empty-result phrases without a key triggers a confirmation prompt.

    Declining stops the search early and returns whatever URLs were already found.
    """
    import main as main_module

    mgr = manager(search_engine="duckduckgo")
    mgr.serpapi_key = None
    monkeypatch.setattr(search_engines.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(mgr, "_search_online", lambda q, attempt=0: [])
    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: False)

    phrases = ["p1", "p2", "p3", "p4", "p5"]
    urls = mgr._search_all_phrases(phrases, max_sources=10)
    assert urls == []


def test_search_all_phrases_consecutive_failures_prompt_and_continue(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirming 'continue' after 3 consecutive failures resets the failure counter and proceeds."""
    import main as main_module

    mgr = manager(search_engine="duckduckgo")
    mgr.serpapi_key = None
    monkeypatch.setattr(search_engines.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(mgr, "_search_online", lambda q, attempt=0: [])
    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: True)

    phrases = ["p1", "p2", "p3", "p4"]
    urls = mgr._search_all_phrases(phrases, max_sources=10)
    assert urls == []


# --- _search_academic_apis ---


def test_search_academic_apis_merges_crossref_and_arxiv(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Results from CrossRef and arXiv are combined into a deduplicated list."""
    mgr = manager()
    monkeypatch.setattr(mgr, "_search_crossref", lambda q: ["https://doi.org/1"])
    monkeypatch.setattr(mgr, "_search_arxiv", lambda q: ["https://arxiv.org/abs/1"])
    urls = mgr._search_academic_apis("query")
    assert set(urls) == {"https://doi.org/1", "https://arxiv.org/abs/1"}


def test_search_academic_apis_swallows_individual_failures(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If one of the academic API searches raises, the other's results are still returned."""
    mgr = manager()

    def _boom(q: str) -> List[str]:
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(mgr, "_search_crossref", _boom)
    monkeypatch.setattr(mgr, "_search_arxiv", lambda q: ["https://arxiv.org/abs/2"])
    urls = mgr._search_academic_apis("query")
    assert urls == ["https://arxiv.org/abs/2"]


# --- _search_crossref ---


def test_search_crossref_returns_doi_urls(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful CrossRef response yields DOI-based URLs."""
    mgr = manager()
    payload = {"message": {"items": [{"DOI": "10.1/abc"}, {"DOI": "10.1/def"}]}}
    monkeypatch.setattr(
        search_engines.requests, "get", lambda *a, **k: FakeResponse(200, json_data=payload)
    )
    urls = mgr._search_crossref("query")
    assert urls == ["https://doi.org/10.1/abc", "https://doi.org/10.1/def"]


def test_search_crossref_non_200_returns_empty(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-200 CrossRef response returns an empty list."""
    mgr = manager()
    monkeypatch.setattr(search_engines.requests, "get", lambda *a, **k: FakeResponse(500))
    assert mgr._search_crossref("query") == []


def test_search_crossref_request_exception_returns_empty(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network error during a CrossRef request returns an empty list."""
    mgr = manager()

    def _boom(*a: object, **k: object) -> None:
        raise requests.exceptions.RequestException("simulated network error")

    monkeypatch.setattr(search_engines.requests, "get", _boom)
    assert mgr._search_crossref("query") == []


def test_search_crossref_uses_configured_contact_email_url_encoded(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CrossRef request URL carries the configured contact email, URL-encoded."""
    mgr = manager()
    monkeypatch.setattr(search_engines, "get_contact_email", lambda: "a b@example.com")
    requested_urls: List[str] = []

    def _fake_get(url: str, *a: object, **k: object) -> FakeResponse:
        requested_urls.append(url)
        return FakeResponse(200, json_data={"message": {"items": []}})

    monkeypatch.setattr(search_engines.requests, "get", _fake_get)
    mgr._search_crossref("query")
    assert requested_urls
    assert "mailto=a%20b%40example.com" in requested_urls[0]


# --- _search_arxiv ---


ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>http://arxiv.org/abs/1111.1111</id></entry>
  <entry><id>http://arxiv.org/abs/2222.2222</id></entry>
</feed>
"""


def test_search_arxiv_parses_entries(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful arXiv response yields the entry ids as URLs."""
    mgr = manager()
    monkeypatch.setattr(
        search_engines.requests,
        "get",
        lambda *a, **k: FakeResponse(200, content=ARXIV_XML.encode("utf-8")),
    )
    urls = mgr._search_arxiv("query")
    assert urls == ["http://arxiv.org/abs/1111.1111", "http://arxiv.org/abs/2222.2222"]


def test_search_arxiv_non_200_returns_empty(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-200 arXiv response returns an empty list."""
    mgr = manager()
    monkeypatch.setattr(search_engines.requests, "get", lambda *a, **k: FakeResponse(503))
    assert mgr._search_arxiv("query") == []


def test_search_arxiv_request_exception_returns_empty(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network error during an arXiv request returns an empty list."""
    mgr = manager()

    def _boom(*a: object, **k: object) -> None:
        raise requests.exceptions.RequestException("simulated network error")

    monkeypatch.setattr(search_engines.requests, "get", _boom)
    assert mgr._search_arxiv("query") == []


# --- _search_online ---


def test_search_online_delegates_to_serpapi_when_key_present(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a SerpApi key is configured, _search_online always delegates to _search_serpapi."""
    mgr = manager()
    mgr.serpapi_key = "KEY"
    monkeypatch.setattr(mgr, "_search_serpapi", lambda q: ["https://serp.example/1"])
    assert mgr._search_online("query") == ["https://serp.example/1"]


def test_search_online_serpapi_engine_without_key_returns_empty(
    manager: Callable[..., SearchEngineManager]
) -> None:
    """search_engine='serpapi' with no key configured returns an empty list without crashing."""
    mgr = manager(search_engine="serpapi")
    mgr.serpapi_key = None
    assert mgr._search_online("query") == []


def test_search_online_duckduckgo_sets_failed_flag_on_empty_results(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty DuckDuckGo result sets the duckduckgo_failed flag."""
    mgr = manager(search_engine="duckduckgo")
    mgr.serpapi_key = None
    monkeypatch.setattr(mgr, "_search_duckduckgo", lambda q, attempt=0: [])
    assert mgr._search_online("query") == []
    assert mgr.duckduckgo_failed is True


def test_search_online_unknown_engine_returns_empty(
    manager: Callable[..., SearchEngineManager]
) -> None:
    """An unrecognized search_engine value returns an empty list."""
    mgr = manager(search_engine="auto")
    mgr.serpapi_key = None
    mgr.search_engine = "bogus"
    assert mgr._search_online("query") == []


# --- _search_serpapi ---


def test_search_serpapi_returns_filtered_organic_results(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Organic results are returned, excluding socially-blocked domains."""
    mgr = manager()
    mgr.serpapi_key = "KEY"
    payload = {
        "organic_results": [
            {"link": "https://example.com/a"},
            {"link": "https://www.youtube.com/watch"},
        ]
    }
    monkeypatch.setattr(
        search_engines.requests, "get", lambda *a, **k: FakeResponse(200, json_data=payload)
    )
    urls = mgr._search_serpapi("query")
    assert urls == ["https://example.com/a"]


def test_search_serpapi_no_key_returns_empty(
    manager: Callable[..., SearchEngineManager]
) -> None:
    """Calling _search_serpapi with no key set returns an empty list immediately."""
    mgr = manager()
    mgr.serpapi_key = None
    assert mgr._search_serpapi("query") == []


def test_search_serpapi_rate_limit_returns_empty(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 429 response returns an empty list without invalidating the key."""
    mgr = manager()
    mgr.serpapi_key = "KEY"
    monkeypatch.setattr(search_engines.requests, "get", lambda *a, **k: FakeResponse(429))
    assert mgr._search_serpapi("query") == []
    assert mgr.serpapi_key == "KEY"


def test_search_serpapi_invalid_key_clears_it(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 401 response clears the stored (now known-invalid) API key."""
    mgr = manager()
    mgr.serpapi_key = "KEY"
    monkeypatch.setattr(search_engines.requests, "get", lambda *a, **k: FakeResponse(401))
    assert mgr._search_serpapi("query") == []
    assert mgr.serpapi_key is None


def test_search_serpapi_other_error_code_returns_empty(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any other non-200 status code returns an empty list."""
    mgr = manager()
    mgr.serpapi_key = "KEY"
    monkeypatch.setattr(search_engines.requests, "get", lambda *a, **k: FakeResponse(500))
    assert mgr._search_serpapi("query") == []


def test_search_serpapi_request_exception_returns_empty(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network error during the SerpApi request returns an empty list."""
    mgr = manager()
    mgr.serpapi_key = "KEY"

    def _boom(*a: object, **k: object) -> None:
        raise requests.exceptions.RequestException("simulated network error")

    monkeypatch.setattr(search_engines.requests, "get", _boom)
    assert mgr._search_serpapi("query") == []


def test_search_serpapi_malformed_json_returns_empty(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A response whose .json() raises ValueError returns an empty list."""
    mgr = manager()
    mgr.serpapi_key = "KEY"
    monkeypatch.setattr(
        search_engines.requests,
        "get",
        lambda *a, **k: FakeResponse(200, json_data=ValueError("bad json")),
    )
    assert mgr._search_serpapi("query") == []


# --- _search_duckduckgo ---


DDG_HTML = """
<html><body>
<a class="result__a" href="https://example.com/page1">Result 1</a>
<a class="result__a" href="https://www.facebook.com/page">Blocked</a>
</body></html>
"""


def test_search_duckduckgo_parses_results(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful DuckDuckGo response returns non-excluded result links."""
    mgr = manager()
    monkeypatch.setattr(mgr.session, "get", lambda *a, **k: FakeResponse(200, text=DDG_HTML))
    urls = mgr._search_duckduckgo("query")
    assert urls == ["https://example.com/page1"]


def test_search_duckduckgo_rate_limited_sets_failed_flag(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 202/429 response marks DuckDuckGo as failed and returns no results."""
    mgr = manager()
    monkeypatch.setattr(mgr.session, "get", lambda *a, **k: FakeResponse(202))
    urls = mgr._search_duckduckgo("query")
    assert urls == []
    assert mgr.duckduckgo_failed is True


def test_search_duckduckgo_retries_then_succeeds(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient connection error is retried once before succeeding."""
    mgr = manager()
    monkeypatch.setattr(search_engines.time, "sleep", lambda *a, **k: None)

    calls = {"count": 0}

    def _get(*a: object, **k: object) -> FakeResponse:
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.exceptions.RequestException("simulated timeout")
        return FakeResponse(200, text=DDG_HTML)

    monkeypatch.setattr(mgr.session, "get", _get)
    urls = mgr._search_duckduckgo("query")
    assert urls == ["https://example.com/page1"]
    assert calls["count"] == 2


def test_search_duckduckgo_exhausts_retries_returns_empty(
    manager: Callable[..., SearchEngineManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated connection errors across both retries return an empty list."""
    mgr = manager()
    monkeypatch.setattr(search_engines.time, "sleep", lambda *a, **k: None)

    def _boom(*a: object, **k: object) -> None:
        raise requests.exceptions.RequestException("simulated timeout")

    monkeypatch.setattr(mgr.session, "get", _boom)
    urls = mgr._search_duckduckgo("query")
    assert urls == []
