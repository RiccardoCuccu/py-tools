"""Tests for phrase_selector.PhraseSelector: TF-IDF based key phrase extraction."""

import builtins
import importlib
import sys
from typing import List

import nltk
import pytest

import phrase_selector
from phrase_selector import PhraseSelector


# --- helpers ---


def _sentence(n_words: int, tag: str) -> str:
    """Build a sentence with n_words distinct meaningful words, tagged for identification."""
    words = [f"{tag}word{i}" for i in range(n_words)]
    return " ".join(words) + "."


# --- basic extraction ---


def test_extract_key_phrases_filters_by_sentence_length() -> None:
    """Sentences outside the [min_phrase_words, 20] word range are dropped."""
    selector = PhraseSelector(min_phrase_words=8, num_phrases=5)
    short = "too short."
    long_ok = _sentence(10, "keep")
    text = f"{short} {long_ok}"
    phrases = selector.extract_key_phrases(text)
    assert any("keepword0" in p for p in phrases)
    assert not any(p.strip() == short for p in phrases)


def test_extract_key_phrases_returns_all_when_fewer_than_target() -> None:
    """When filtered sentences are fewer than num_phrases, all of them are returned."""
    selector = PhraseSelector(min_phrase_words=5, num_phrases=10)
    sentences = [_sentence(6, f"s{i}") for i in range(3)]
    text = " ".join(sentences)
    phrases = selector.extract_key_phrases(text)
    assert len(phrases) == 3


def test_extract_key_phrases_no_suitable_sentences_falls_back_to_raw_text() -> None:
    """If no sentence survives filtering, the first 200 chars of the raw text are returned."""
    selector = PhraseSelector(min_phrase_words=8, num_phrases=5)
    text = "one two three."
    phrases = selector.extract_key_phrases(text)
    assert phrases == [text[:200]]


def test_extract_key_phrases_selects_top_n_via_tfidf() -> None:
    """When candidates exceed num_phrases, TF-IDF scoring selects exactly num_phrases sentences."""
    selector = PhraseSelector(min_phrase_words=5, num_phrases=3)
    sentences = [_sentence(8, f"topic{i}") for i in range(10)]
    text = " ".join(sentences)
    phrases = selector.extract_key_phrases(text)
    assert len(phrases) == 3


def test_extract_key_phrases_preserves_document_order() -> None:
    """Selected phrases stay in their original document order, not TF-IDF score order."""
    selector = PhraseSelector(min_phrase_words=5, num_phrases=3)
    sentences = [_sentence(8, f"topic{i}") for i in range(10)]
    text = " ".join(sentences)
    phrases = selector.extract_key_phrases(text)
    indices = [sentences.index(p) for p in phrases]
    assert indices == sorted(indices)


def test_extract_key_phrases_auto_scales_without_explicit_num_phrases() -> None:
    """With num_phrases=None, the target is auto-scaled to at least 5 phrases."""
    selector = PhraseSelector(min_phrase_words=5, num_phrases=None)
    sentences = [_sentence(8, f"auto{i}") for i in range(20)]
    text = " ".join(sentences)
    phrases = selector.extract_key_phrases(text)
    assert len(phrases) >= 5


# --- num_phrases=0 (extract ALL) ---


def test_extract_key_phrases_zero_confirms_and_returns_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """num_phrases=0 requests confirmation, then returns every filtered sentence."""
    import main as main_module

    monkeypatch.setattr(main_module, "confirm_continue", lambda *a, **k: True)

    selector = PhraseSelector(min_phrase_words=5, num_phrases=0)
    sentences = [_sentence(8, f"all{i}") for i in range(6)]
    text = " ".join(sentences)
    phrases = selector.extract_key_phrases(text)
    assert len(phrases) == 6


def test_extract_key_phrases_zero_exits_when_user_declines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """num_phrases=0 exits (via confirm_continue) when the user declines to continue."""
    import main as main_module

    def _decline(*args: object, **kwargs: object) -> bool:
        raise SystemExit(0)

    monkeypatch.setattr(main_module, "confirm_continue", _decline)

    selector = PhraseSelector(min_phrase_words=5, num_phrases=0)
    sentences = [_sentence(8, f"all{i}") for i in range(6)]
    text = " ".join(sentences)
    with pytest.raises(SystemExit):
        selector.extract_key_phrases(text)


# --- TF-IDF failure fallback ---


def test_extract_key_phrases_tfidf_failure_falls_back_to_uniform_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If TF-IDF scoring raises, phrases are chosen via uniform-step distribution instead."""

    def _boom(*args: object, **kwargs: object) -> None:
        raise ValueError("simulated empty vocabulary")

    monkeypatch.setattr(phrase_selector, "TfidfVectorizer", _boom)

    selector = PhraseSelector(min_phrase_words=5, num_phrases=3)
    sentences = [_sentence(8, f"topic{i}") for i in range(9)]
    text = " ".join(sentences)
    phrases: List[str] = selector.extract_key_phrases(text)

    step = 9 // 3
    expected = [sentences[i * step] for i in range(3)]
    assert phrases == expected


# --- module-level NLTK data / import guards (no network) ---


def test_module_downloads_nltk_data_when_missing_without_hitting_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If required NLTK data is reported missing, the module calls nltk.download (mocked, no network)."""

    def _always_missing(*args: object, **kwargs: object) -> None:
        raise LookupError("simulated missing NLTK data")

    download_calls: List[str] = []

    def _fake_download(name: str, quiet: bool = False) -> bool:
        download_calls.append(name)
        return True

    monkeypatch.setattr(nltk.data, "find", _always_missing)
    monkeypatch.setattr(nltk, "download", _fake_download)

    try:
        importlib.reload(phrase_selector)
    finally:
        # Restore normal module state (real NLTK data is present locally).
        monkeypatch.undo()
        importlib.reload(phrase_selector)

    assert "punkt_tab" in download_calls
    assert "stopwords" in download_calls


def test_module_exits_when_required_library_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If sklearn/nltk cannot be imported, the module prints guidance and exits with code 1."""
    real_import = builtins.__import__

    def _blocking_import(name: str, *args: object, **kwargs: object):
        if name == "sklearn.feature_extraction.text":
            raise ImportError("simulated missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocking_import)
    monkeypatch.delitem(sys.modules, "phrase_selector")

    try:
        with pytest.raises(SystemExit) as excinfo:
            import phrase_selector  # noqa: F401
        assert excinfo.value.code == 1
    finally:
        monkeypatch.undo()
        sys.modules.pop("phrase_selector", None)
        importlib.import_module("phrase_selector")
