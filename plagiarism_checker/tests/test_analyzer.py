"""Tests for analyzer.SimilarityAnalyzer: TF-IDF similarity scoring and report generation."""

from pathlib import Path
from typing import Callable, List

import analyzer
from analyzer import SimilarityAnalyzer


# --- fixtures ---


def make_analyzer(tmp_path: Path, doc_name: str = "doc.docx") -> SimilarityAnalyzer:
    """Build a SimilarityAnalyzer whose report is written under tmp_path, not the script dir."""
    doc_path = tmp_path / doc_name
    doc_path.write_text("placeholder")
    inst = SimilarityAnalyzer(doc_path)
    inst.script_dir = tmp_path
    return inst


def _sentence(n_words: int, tag: str) -> str:
    """Build a sentence with n_words distinct words, tagged for identification."""
    return " ".join(f"{tag}word{i}" for i in range(n_words)) + "."


# --- _calculate_similarity ---


def test_calculate_similarity_identical_texts_scores_high(tmp_path: Path) -> None:
    """Identical text compared to itself scores a high similarity."""
    inst = make_analyzer(tmp_path)
    text = " ".join(_sentence(8, f"s{i}") for i in range(5))
    score = inst._calculate_similarity(text, text)
    assert score > 0.9


def test_calculate_similarity_unrelated_texts_scores_low(tmp_path: Path) -> None:
    """Completely unrelated vocabularies score near zero similarity."""
    inst = make_analyzer(tmp_path)
    text1 = " ".join(_sentence(8, f"alpha{i}") for i in range(5))
    text2 = " ".join(_sentence(8, f"beta{i}") for i in range(5))
    score = inst._calculate_similarity(text1, text2)
    assert score < 0.3


def test_calculate_similarity_empty_vocabulary_returns_zero(tmp_path: Path) -> None:
    """When TF-IDF raises (e.g. empty vocabulary after stopword removal), 0.0 is returned."""
    inst = make_analyzer(tmp_path)
    score = inst._calculate_similarity("", "")
    assert score == 0.0


# --- _find_matching_segments ---


def test_find_matching_segments_detects_near_identical_sentences(tmp_path: Path) -> None:
    """A sentence repeated verbatim in the source text is detected as a match."""
    inst = make_analyzer(tmp_path)
    shared = _sentence(10, "shared")
    doc_text = f"Intro words that differ entirely. {shared}"
    source_text = f"{shared} Some unrelated trailing text words here."
    matches = inst._find_matching_segments(doc_text, source_text, threshold=0.7)
    assert len(matches) >= 1
    assert matches[0]["similarity"] >= 0.7


def test_find_matching_segments_no_match_below_threshold(tmp_path: Path) -> None:
    """Completely dissimilar sentences produce no matches."""
    inst = make_analyzer(tmp_path)
    doc_text = _sentence(8, "docwords") + " " + _sentence(8, "docmorewords")
    source_text = _sentence(8, "sourceonly") + " " + _sentence(8, "sourceother")
    matches = inst._find_matching_segments(doc_text, source_text, threshold=0.7)
    assert matches == []


def test_find_matching_segments_empty_doc_sentences_returns_empty(tmp_path: Path) -> None:
    """No usable (>=5 word) sentences in the document short-circuits to an empty list."""
    inst = make_analyzer(tmp_path)
    matches = inst._find_matching_segments("Hi. Ok.", "Some real sentence with enough words here.")
    assert matches == []


def test_find_matching_segments_empty_source_sentences_returns_empty(tmp_path: Path) -> None:
    """No usable (>=5 word) sentences in the source short-circuits to an empty list."""
    inst = make_analyzer(tmp_path)
    matches = inst._find_matching_segments("Some real sentence with enough words here.", "Hi. Ok.")
    assert matches == []


def test_find_matching_segments_tfidf_failure_returns_empty(tmp_path: Path) -> None:
    """If TF-IDF scoring raises (e.g. empty vocabulary), matching falls back to an empty list."""
    inst = make_analyzer(tmp_path)
    stopword_sentence = "the a an of it is on at as be for."
    matches = inst._find_matching_segments(stopword_sentence, stopword_sentence)
    assert matches == []


# --- analyze_sources ---


def test_analyze_sources_includes_and_sorts_by_similarity(tmp_path: Path) -> None:
    """Sources are included when similar enough and sorted by descending similarity."""
    inst = make_analyzer(tmp_path)
    shared = _sentence(10, "sharedphrase")
    doc_text = f"{shared} " * 3

    strong_source = {"url": "http://strong.example", "title": "Strong", "content": f"{shared} " * 3}
    weak_source = {
        "url": "http://weak.example",
        "title": "Weak",
        "content": " ".join(_sentence(8, f"unrelated{i}") for i in range(5)),
    }

    results = inst.analyze_sources(doc_text, [weak_source, strong_source])
    urls = [r["url"] for r in results]
    assert urls[0] == "http://strong.example"


def test_analyze_sources_excludes_dissimilar_sources_below_threshold(tmp_path: Path) -> None:
    """A source with negligible similarity and no matching segments is excluded from results."""
    inst = make_analyzer(tmp_path)
    doc_text = " ".join(_sentence(8, f"docfoo{i}") for i in range(5))
    unrelated_source = {
        "url": "http://unrelated.example",
        "title": "Unrelated",
        "content": " ".join(_sentence(8, f"barbaz{i}") for i in range(5)),
    }
    results = inst.analyze_sources(doc_text, [unrelated_source])
    assert results == []


def test_analyze_sources_local_result_includes_file_fields(tmp_path: Path) -> None:
    """Local sources carry file_name/file_path fields in addition to the shared fields."""
    inst = make_analyzer(tmp_path)
    shared = _sentence(10, "localshared")
    doc_text = f"{shared} " * 3
    local_source = {
        "file_path": "/refs/local.txt",
        "file_name": "local.txt",
        "content": f"{shared} " * 3,
        "is_local": True,
    }
    results = inst.analyze_sources(doc_text, [local_source])
    assert len(results) == 1
    assert results[0]["is_local"] is True
    assert results[0]["file_name"] == "local.txt"
    assert results[0]["file_path"] == "/refs/local.txt"


# --- generate_report ---


def test_generate_report_no_results_section(tmp_path: Path) -> None:
    """With no results, the report states no significant matches were found."""
    inst = make_analyzer(tmp_path, doc_name="clean.docx")
    inst.generate_report([], "document text here")
    report_file = tmp_path / "clean_plagiarism_report.txt"
    assert report_file.exists()
    text = report_file.read_text(encoding="utf-8")
    assert "NO SIGNIFICANT MATCHES FOUND" in text


def test_generate_report_high_similarity_status(tmp_path: Path) -> None:
    """A top similarity above 0.5 is flagged as HIGH SIMILARITY DETECTED."""
    inst = make_analyzer(tmp_path, doc_name="high.docx")
    results = [
        {
            "overall_similarity": 0.75,
            "matching_segments": 2,
            "matches": [{"doc_text": "doc sentence", "source_text": "source sentence", "similarity": 0.9}],
            "is_local": False,
            "url": "http://example.com/a",
            "title": "Source A",
        }
    ]
    inst.generate_report(results, "document text here")
    text = (tmp_path / "high_plagiarism_report.txt").read_text(encoding="utf-8")
    assert "HIGH SIMILARITY DETECTED" in text
    assert "ONLINE SOURCES" in text
    assert "http://example.com/a" in text


def test_generate_report_moderate_similarity_status(tmp_path: Path) -> None:
    """A top similarity between 0.3 and 0.5 is flagged as MODERATE SIMILARITY DETECTED."""
    inst = make_analyzer(tmp_path, doc_name="moderate.docx")
    results = [
        {
            "overall_similarity": 0.4,
            "matching_segments": 0,
            "matches": [],
            "is_local": False,
            "url": "http://example.com/b",
            "title": "Source B",
        }
    ]
    inst.generate_report(results, "document text here")
    text = (tmp_path / "moderate_plagiarism_report.txt").read_text(encoding="utf-8")
    assert "MODERATE SIMILARITY DETECTED" in text


def test_generate_report_low_similarity_status(tmp_path: Path) -> None:
    """A top similarity below 0.3 is flagged as LOW SIMILARITY."""
    inst = make_analyzer(tmp_path, doc_name="low.docx")
    results = [
        {
            "overall_similarity": 0.05,
            "matching_segments": 0,
            "matches": [],
            "is_local": False,
            "url": "http://example.com/c",
            "title": "Source C",
        }
    ]
    inst.generate_report(results, "document text here")
    text = (tmp_path / "low_plagiarism_report.txt").read_text(encoding="utf-8")
    assert "LOW SIMILARITY" in text


def test_generate_report_local_and_online_sections(tmp_path: Path) -> None:
    """Local and online results are rendered under their respective section headers."""
    inst = make_analyzer(tmp_path, doc_name="both.docx")
    results = [
        {
            "overall_similarity": 0.6,
            "matching_segments": 1,
            "matches": [{"doc_text": "doc sentence", "source_text": "local source sentence", "similarity": 0.8}],
            "is_local": True,
            "url": "/local/ref.txt",
            "title": "ref.txt",
            "file_name": "ref.txt",
            "file_path": "/local/ref.txt",
        },
        {
            "overall_similarity": 0.5,
            "matching_segments": 1,
            "matches": [],
            "is_local": False,
            "url": "http://example.com/d",
            "title": "Source D",
        },
    ]
    inst.generate_report(results, "document text here")
    text = (tmp_path / "both_plagiarism_report.txt").read_text(encoding="utf-8")
    assert "LOCAL REFERENCE FILES" in text
    assert "ONLINE SOURCES" in text
    assert "ref.txt" in text
    assert "http://example.com/d" in text
    assert "Sample Matches:" in text
    assert "local source sentence" in text


def test_generate_report_downloaded_sources_section(tmp_path: Path) -> None:
    """The DOWNLOADED SOURCES section lists every fetched source, regardless of similarity filtering."""
    inst = make_analyzer(tmp_path, doc_name="downloaded.docx")
    downloaded_sources = [
        {"url": "http://example.com/x", "title": "Fetched X"},
        {"url": "http://example.com/y", "title": "Fetched Y"},
    ]
    inst.generate_report([], "document text here", downloaded_sources=downloaded_sources)
    text = (tmp_path / "downloaded_plagiarism_report.txt").read_text(encoding="utf-8")
    assert "DOWNLOADED SOURCES" in text
    assert "http://example.com/x" in text
    assert "http://example.com/y" in text


def test_generate_report_omits_downloaded_sources_section_when_absent(tmp_path: Path) -> None:
    """No DOWNLOADED SOURCES section appears when downloaded_sources is empty/None."""
    inst = make_analyzer(tmp_path, doc_name="nodown.docx")
    inst.generate_report([], "document text here")
    text = (tmp_path / "nodown_plagiarism_report.txt").read_text(encoding="utf-8")
    assert "DOWNLOADED SOURCES" not in text


def test_generate_report_failed_sources_section(tmp_path: Path) -> None:
    """Failed downloads are listed under SOURCES NOT DOWNLOADED with their reason."""
    inst = make_analyzer(tmp_path, doc_name="failed.docx")
    failed_sources = [{"url": "http://example.com/broken", "reason": "Timeout after 15s"}]
    inst.generate_report([], "document text here", failed_sources=failed_sources)
    text = (tmp_path / "failed_plagiarism_report.txt").read_text(encoding="utf-8")
    assert "SOURCES NOT DOWNLOADED" in text
    assert "http://example.com/broken" in text
    assert "Timeout after 15s" in text


def test_generate_report_always_includes_limitations(tmp_path: Path) -> None:
    """The LIMITATIONS section is always present, regardless of results."""
    inst = make_analyzer(tmp_path, doc_name="limits.docx")
    inst.generate_report([], "document text here")
    text = (tmp_path / "limits_plagiarism_report.txt").read_text(encoding="utf-8")
    assert "LIMITATIONS" in text
    assert "Does NOT detect paraphrasing" in text
