"""Tests for main.py: CLI parsing, file validation, and the PlagiarismChecker orchestration."""

from pathlib import Path
from typing import Any, Callable, List, Optional
from unittest.mock import MagicMock

import pytest

import main
from main import MIN_DOCUMENT_LENGTH, PlagiarismChecker, confirm_continue, validate_file


# --- confirm_continue ---


def test_confirm_continue_yes_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 'y' response returns True."""
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    assert confirm_continue() is True


def test_confirm_continue_yes_full_word_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 'yes' response (case-insensitive) returns True."""
    monkeypatch.setattr("builtins.input", lambda *a, **k: "YES")
    assert confirm_continue() is True


def test_confirm_continue_no_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """An 'n' response exits the program with code 0."""
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    with pytest.raises(SystemExit) as excinfo:
        confirm_continue()
    assert excinfo.value.code == 0


def test_confirm_continue_reprompts_on_invalid_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid input is rejected and the prompt repeats until a valid answer is given."""
    responses = iter(["maybe", "sure", "y"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(responses))
    assert confirm_continue() is True


# --- validate_file ---


def test_validate_file_missing_exits(tmp_path: Path) -> None:
    """A nonexistent file path exits with code 1."""
    with pytest.raises(SystemExit) as excinfo:
        validate_file(tmp_path / "missing.txt")
    assert excinfo.value.code == 1


def test_validate_file_directory_exits(tmp_path: Path) -> None:
    """A path pointing at a directory (not a file) exits with code 1."""
    with pytest.raises(SystemExit) as excinfo:
        validate_file(tmp_path)
    assert excinfo.value.code == 1


def test_validate_file_unreadable_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file that fails the read-access check exits with code 1."""
    path = tmp_path / "unreadable.txt"
    path.write_text("content")
    monkeypatch.setattr(main.os, "access", lambda *a, **k: False)
    with pytest.raises(SystemExit) as excinfo:
        validate_file(path)
    assert excinfo.value.code == 1


def test_validate_file_empty_exits(tmp_path: Path) -> None:
    """A zero-byte file exits with code 1."""
    path = tmp_path / "empty.txt"
    path.write_text("")
    with pytest.raises(SystemExit) as excinfo:
        validate_file(path)
    assert excinfo.value.code == 1


def test_validate_file_valid_file_passes(tmp_path: Path) -> None:
    """A normal, readable, non-empty file passes validation without raising."""
    path = tmp_path / "valid.txt"
    path.write_text("some content")
    validate_file(path)  # should not raise


def test_validate_file_large_file_prompts_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file above the size threshold triggers a confirmation prompt before continuing."""
    path = tmp_path / "large.txt"
    path.write_text("x")
    monkeypatch.setattr(main, "MAX_FILE_SIZE_BYTES", 0)
    monkeypatch.setattr(main, "confirm_continue", lambda *a, **k: True)
    validate_file(path)  # should not raise


# --- PlagiarismChecker orchestration (components faked to avoid real I/O/network) ---


class _FakeExtractor:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def extract_text(self) -> str:
        return "x" * MIN_DOCUMENT_LENGTH


class _FakePhraseSelector:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def extract_key_phrases(self, text: str) -> List[str]:
        return ["phrase one", "phrase two"]


class _FakeSearchManager:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.serpapi_key: Optional[str] = "KEY"
        self.local_sources: List[dict] = []

    def search_and_load(self, phrases: List[str], max_sources: int) -> tuple:
        return (["http://a.example"], [])


class _FakeDownloader:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def get_all_cached_sources(self) -> List[dict]:
        return []

    def download_all_sources(self, urls: List[str]) -> tuple:
        return ([], [])


class _FakeAnalyzer:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.generate_report_calls: List[tuple] = []

    def analyze_sources(self, doc_text: str, sources: List[dict]) -> List[dict]:
        return [{"overall_similarity": 0.1}]

    def generate_report(self, *args: object, **kwargs: object) -> None:
        pass


@pytest.fixture
def fake_components(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every PlagiarismChecker component with a lightweight fake (no real I/O/network)."""
    monkeypatch.setattr(main, "TextExtractor", _FakeExtractor)
    monkeypatch.setattr(main, "PhraseSelector", _FakePhraseSelector)
    monkeypatch.setattr(main, "SearchEngineManager", _FakeSearchManager)
    monkeypatch.setattr(main, "ContentDownloader", _FakeDownloader)
    monkeypatch.setattr(main, "SimilarityAnalyzer", _FakeAnalyzer)


def _build_checker(tmp_path: Path, **kwargs: Any) -> PlagiarismChecker:
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("document content")
    return PlagiarismChecker(doc_path, **kwargs)


def test_checker_init_stores_configuration(tmp_path: Path, fake_components: None) -> None:
    """__init__ stores all configuration parameters on the instance."""
    checker = _build_checker(
        tmp_path, max_sources=7, extract_pages=2, page_position="start", num_phrases=3,
        use_apis=True, use_local=True, search_engine="serpapi", cache_only=True,
    )
    assert checker.max_sources == 7
    assert checker.extract_pages == 2
    assert checker.page_position == "start"
    assert checker.num_phrases == 3
    assert checker.use_apis is True
    assert checker.use_local is True
    assert checker.search_engine == "serpapi"
    assert checker.cache_only is True


def test_check_exits_when_document_too_short(
    tmp_path: Path, fake_components: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A document below MIN_DOCUMENT_LENGTH exits with code 1."""
    checker = _build_checker(tmp_path, extract_pages=1, cache_only=True)
    checker.extractor.extract_text = lambda: "too short"
    with pytest.raises(SystemExit) as excinfo:
        checker.check()
    assert excinfo.value.code == 1


def test_check_cache_only_skips_search_and_uses_all_cached_sources(
    tmp_path: Path, fake_components: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--cache-only skips the search step and loads every cached source (regression for the bug fix)."""
    checker = _build_checker(tmp_path, extract_pages=1, cache_only=True)
    checker.search_manager.search_and_load = MagicMock(
        side_effect=AssertionError("search must not run in cache-only mode")
    )
    checker.downloader.get_all_cached_sources = MagicMock(
        return_value=[{"url": "cached://h1", "content": "x" * 300, "title": "Cached"}]
    )
    checker.analyzer.generate_report = MagicMock()

    checker.check()

    checker.downloader.get_all_cached_sources.assert_called_once()
    checker.analyzer.generate_report.assert_called_once()


def test_check_no_online_sources_found_exits_zero(
    tmp_path: Path, fake_components: None
) -> None:
    """No online sources found (non-cache-only) exits cleanly with code 0."""
    checker = _build_checker(tmp_path, extract_pages=1, cache_only=False, use_local=True)
    checker.search_manager.search_and_load = lambda phrases, max_sources: ([], [])
    with pytest.raises(SystemExit) as excinfo:
        checker.check()
    assert excinfo.value.code == 0


def test_check_no_sources_at_all_exits_zero(
    tmp_path: Path, fake_components: None
) -> None:
    """When both local and downloaded sources are empty, the run exits with code 0."""
    checker = _build_checker(tmp_path, extract_pages=1, cache_only=False, use_local=True)
    checker.search_manager.search_and_load = lambda phrases, max_sources: (["http://a"], [])
    checker.downloader.download_all_sources = lambda urls: ([], [])
    with pytest.raises(SystemExit) as excinfo:
        checker.check()
    assert excinfo.value.code == 0


def test_check_full_flow_calls_generate_report(
    tmp_path: Path, fake_components: None
) -> None:
    """A normal successful run reaches analyze_sources and generate_report."""
    checker = _build_checker(tmp_path, extract_pages=1, cache_only=False, use_local=False)
    checker.downloader.download_all_sources = lambda urls: (
        [{"url": "http://a", "content": "x" * 300, "title": "A"}],
        [],
    )
    checker.analyzer.generate_report = MagicMock()
    checker.check()
    checker.analyzer.generate_report.assert_called_once()


def test_check_warns_when_analyzing_full_document(
    tmp_path: Path, fake_components: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without --pages, the user is warned and prompted before continuing."""
    checker = _build_checker(tmp_path, extract_pages=None, cache_only=True)
    prompts: List[str] = []

    def _confirm(message: str = "Do you want to continue?") -> bool:
        prompts.append(message)
        return True

    monkeypatch.setattr(main, "confirm_continue", _confirm)
    checker.downloader.get_all_cached_sources = lambda: [
        {"url": "cached://h1", "content": "x" * 300, "title": "Cached"}
    ]
    checker.check()
    assert prompts  # confirm_continue was invoked at least once


def test_check_warns_when_no_serpapi_key_and_not_local_or_cache_only(
    tmp_path: Path, fake_components: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No SerpApi key, not local-only, not cache-only: user is warned and prompted."""
    checker = _build_checker(tmp_path, extract_pages=1, cache_only=False, use_local=False)
    checker.search_manager.serpapi_key = None
    prompts: List[str] = []

    def _confirm(message: str = "Do you want to continue?") -> bool:
        prompts.append(message)
        return True

    monkeypatch.setattr(main, "confirm_continue", _confirm)
    checker.downloader.download_all_sources = lambda urls: (
        [{"url": "http://a", "content": "x" * 300, "title": "A"}],
        [],
    )
    checker.check()
    assert any("Continue anyway" in p for p in prompts)


# --- main() CLI dispatch ---


def test_main_no_file_argument_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running with no file argument exits with code 1."""
    monkeypatch.setattr("sys.argv", ["main.py"])
    with pytest.raises(SystemExit) as excinfo:
        main.main()
    assert excinfo.value.code == 1


def test_main_rejects_unsupported_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unsupported file extension exits with code 1 before any file access."""
    monkeypatch.setattr("sys.argv", ["main.py", "document.rtf"])
    with pytest.raises(SystemExit) as excinfo:
        main.main()
    assert excinfo.value.code == 1


def test_main_accepts_uppercase_extension_case_insensitively(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: an uppercase .TXT extension is accepted, not rejected as unsupported."""
    path = tmp_path / "document.TXT"
    path.write_text("some content")
    monkeypatch.setattr("sys.argv", ["main.py", str(path)])

    fake_checker_instances: List[Any] = []

    class _FakeChecker:
        def __init__(self, *args: object, **kwargs: object) -> None:
            fake_checker_instances.append(self)

        def check(self) -> None:
            pass

    monkeypatch.setattr(main, "PlagiarismChecker", _FakeChecker)
    main.main()  # must not raise SystemExit for the extension check
    assert len(fake_checker_instances) == 1


def test_main_runs_checker_for_supported_lowercase_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A normal .txt file reaches PlagiarismChecker construction and check()."""
    path = tmp_path / "document.txt"
    path.write_text("some content")
    monkeypatch.setattr("sys.argv", ["main.py", str(path), "--cache-only"])

    check_calls: List[bool] = []

    class _FakeChecker:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def check(self) -> None:
            check_calls.append(True)

    monkeypatch.setattr(main, "PlagiarismChecker", _FakeChecker)
    main.main()
    assert check_calls == [True]


def test_main_reset_serpapi_key_exits_zero_without_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """--reset-serpapi-key prints the result and exits 0 without requiring a file argument."""
    monkeypatch.setattr("sys.argv", ["main.py", "--reset-serpapi-key"])
    monkeypatch.setattr("search_engines.reset_serpapi_key", lambda: "SerpApi key removed from the OS keyring.")

    with pytest.raises(SystemExit) as excinfo:
        main.main()

    assert excinfo.value.code == 0
    assert "removed" in capsys.readouterr().out
