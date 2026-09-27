"""Tests for extractors.TextExtractor: text extraction from .docx, .pdf and .txt files."""

from pathlib import Path
from typing import Callable

import fitz
import pytest
from docx import Document

from extractors import TextExtractor


# --- fixtures ---


@pytest.fixture
def make_docx(tmp_path: Path) -> Callable[[str, str], Path]:
    """Return a factory that writes a .docx file with the given paragraphs text."""

    def _make(name: str, body: str) -> Path:
        doc = Document()
        for line in body.splitlines():
            if line.strip():
                doc.add_paragraph(line)
        path = tmp_path / name
        doc.save(str(path))
        return path

    return _make


@pytest.fixture
def make_pdf(tmp_path: Path) -> Callable[[str, str], Path]:
    """Return a factory that writes a single-page .pdf file containing the given text."""

    def _make(name: str, body: str) -> Path:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), body)
        path = tmp_path / name
        doc.save(str(path))
        doc.close()
        return path

    return _make


@pytest.fixture
def make_txt(tmp_path: Path) -> Callable[[str, str], Path]:
    """Return a factory that writes a plain .txt file with the given content."""

    def _make(name: str, body: str, encoding: str = "utf-8") -> Path:
        path = tmp_path / name
        path.write_text(body, encoding=encoding)
        return path

    return _make


# --- extract_text dispatcher ---


def test_extract_text_dispatches_docx(make_docx: Callable[[str, str], Path]) -> None:
    """A .docx path is routed to the docx extraction branch."""
    path = make_docx("doc.docx", "Hello world paragraph one.\nSecond paragraph here.")
    extractor = TextExtractor(path)
    text = extractor.extract_text()
    assert "Hello world paragraph one." in text
    assert "Second paragraph here." in text


def test_extract_text_dispatches_pdf(make_pdf: Callable[[str, str], Path]) -> None:
    """A .pdf path is routed to the PDF extraction branch."""
    path = make_pdf("doc.pdf", "Hello from PDF content.")
    extractor = TextExtractor(path)
    text = extractor.extract_text()
    assert "Hello from PDF content." in text


def test_extract_text_dispatches_txt(make_txt: Callable[[str, str], Path]) -> None:
    """A .txt path is routed to the plain-text extraction branch."""
    path = make_txt("doc.txt", "Plain text content here.")
    extractor = TextExtractor(path)
    text = extractor.extract_text()
    assert text == "Plain text content here."


def test_extract_text_dispatches_uppercase_extensions(
    make_txt: Callable[[str, str], Path],
) -> None:
    """Extension matching is case-insensitive: .TXT resolves the same as .txt."""
    path = make_txt("DOC.TXT", "Uppercase extension content.")
    extractor = TextExtractor(path)
    text = extractor.extract_text()
    assert text == "Uppercase extension content."


def test_extract_text_empty_txt_file_exits(make_txt: Callable[[str, str], Path]) -> None:
    """An empty .txt file yields falsy text, which triggers a hard exit."""
    path = make_txt("empty.txt", "")
    extractor = TextExtractor(path)
    with pytest.raises(SystemExit) as excinfo:
        extractor.extract_text()
    assert excinfo.value.code == 1


def test_extract_text_unsupported_extension_exits(tmp_path: Path) -> None:
    """An unsupported file extension exits with code 1."""
    path = tmp_path / "doc.xyz"
    path.write_text("content")
    extractor = TextExtractor(path)
    with pytest.raises(SystemExit) as excinfo:
        extractor.extract_text()
    assert excinfo.value.code == 1


# --- _extract_page_range ---


def test_extract_page_range_returns_full_text_when_no_pages_requested() -> None:
    """extract_pages=None returns the text unmodified."""
    extractor = TextExtractor("doc.txt", extract_pages=None)
    text = "x" * 5000
    assert extractor._extract_page_range(text) == text


def test_extract_page_range_start_position_takes_prefix() -> None:
    """position='start' returns the first N*chars_per_page characters."""
    extractor = TextExtractor("doc.txt", extract_pages=1, page_position="start")
    text = "abcdefghij" * 1000  # 10000 chars
    result = extractor._extract_page_range(text, chars_per_page=3000)
    assert result == text[:3000]


def test_extract_page_range_end_position_takes_suffix() -> None:
    """position='end' returns the last N*chars_per_page characters."""
    extractor = TextExtractor("doc.txt", extract_pages=1, page_position="end")
    text = "abcdefghij" * 1000
    result = extractor._extract_page_range(text, chars_per_page=3000)
    assert result == text[-3000:]


def test_extract_page_range_middle_position_centers_the_slice() -> None:
    """position='middle' (default) centers the requested slice within the text."""
    extractor = TextExtractor("doc.txt", extract_pages=1, page_position="middle")
    text = "abcdefghij" * 1000  # 10000 chars
    result = extractor._extract_page_range(text, chars_per_page=3000)
    expected_start = (10000 - 3000) // 2
    assert result == text[expected_start:expected_start + 3000]


def test_extract_page_range_requested_pages_exceed_total_clamps_to_full_text() -> None:
    """Requesting more characters than available clamps to the whole text without error."""
    extractor = TextExtractor("doc.txt", extract_pages=10, page_position="start")
    text = "short text"
    result = extractor._extract_page_range(text, chars_per_page=3000)
    assert result == text


# --- docx extraction with page slicing ---


def test_extract_from_docx_with_page_slicing(make_docx: Callable[[str, str], Path]) -> None:
    """Requesting a page range from a docx returns only the sliced portion."""
    paragraphs = "\n".join(f"Paragraph number {i} with some filler words." for i in range(400))
    path = make_docx("big.docx", paragraphs)
    extractor = TextExtractor(path, extract_pages=1, page_position="start")
    text = extractor.extract_text()
    assert len(text) <= 3000
    assert text.startswith("Paragraph number 0")


def test_extract_from_docx_read_error_exits(tmp_path: Path) -> None:
    """A corrupted .docx file raises inside python-docx and exits with code 1."""
    path = tmp_path / "corrupt.docx"
    path.write_bytes(b"not a real docx file")
    extractor = TextExtractor(path)
    with pytest.raises(SystemExit) as excinfo:
        extractor.extract_text()
    assert excinfo.value.code == 1


# --- pdf extraction with page slicing ---


def test_extract_from_pdf_with_page_slicing(make_pdf: Callable[[str, str], Path]) -> None:
    """Requesting a page range from a PDF returns only the sliced portion."""
    body = "Sentence filler words here. " * 200
    path = make_pdf("big.pdf", body)
    extractor = TextExtractor(path, extract_pages=1, page_position="end")
    text = extractor.extract_text()
    assert len(text) <= 3000


def test_extract_from_pdf_read_error_exits(tmp_path: Path) -> None:
    """A corrupted .pdf file raises inside PyMuPDF and exits with code 1."""
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.4 not a real pdf structure")
    extractor = TextExtractor(path)
    with pytest.raises(SystemExit) as excinfo:
        extractor.extract_text()
    assert excinfo.value.code == 1


# --- txt extraction ---


def test_extract_from_txt_with_page_slicing(make_txt: Callable[[str, str], Path]) -> None:
    """Requesting a page range from a .txt file returns only the sliced portion."""
    body = "word " * 3000
    path = make_txt("big.txt", body)
    extractor = TextExtractor(path, extract_pages=1, page_position="middle")
    text = extractor.extract_text()
    assert len(text) <= 3000


def test_extract_from_txt_handles_non_utf8_bytes_gracefully(tmp_path: Path) -> None:
    """Non-UTF-8 byte sequences are ignored rather than raising UnicodeDecodeError."""
    path = tmp_path / "binary.txt"
    path.write_bytes("Valid start. ".encode("utf-8") + b"\xff\xfe\x00\x80" + "Valid end.".encode("utf-8"))
    extractor = TextExtractor(path)
    text = extractor.extract_text()
    assert "Valid start." in text
    assert "Valid end." in text


def test_extract_from_txt_read_error_returns_none_for_reference_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading a reference (non-main) text file that raises returns None instead of exiting."""
    main_path = tmp_path / "main.txt"
    main_path.write_text("main document text")
    ref_path = tmp_path / "reference.txt"
    ref_path.write_text("reference text")

    extractor = TextExtractor(main_path)

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("simulated read failure")

    monkeypatch.setattr("builtins.open", _boom)
    result = extractor._extract_from_txt(ref_path)
    assert result is None


# --- extract_from_file (reference files) ---


def test_extract_from_file_docx(make_docx: Callable[[str, str], Path]) -> None:
    """extract_from_file reads a reference .docx file in full, ignoring page settings."""
    path = make_docx("ref.docx", "Reference paragraph one.\nReference paragraph two.")
    extractor = TextExtractor("main.docx", extract_pages=1)
    text = extractor.extract_from_file(path)
    assert text == "Reference paragraph one.\nReference paragraph two."


def test_extract_from_file_docx_read_error_returns_none(tmp_path: Path) -> None:
    """A corrupted reference .docx returns None with a warning instead of raising."""
    path = tmp_path / "corrupt_ref.docx"
    path.write_bytes(b"not a docx")
    extractor = TextExtractor("main.docx")
    assert extractor.extract_from_file(path) is None


def test_extract_from_file_pdf(make_pdf: Callable[[str, str], Path]) -> None:
    """extract_from_file reads a reference .pdf file in full."""
    path = make_pdf("ref.pdf", "Reference PDF content.")
    extractor = TextExtractor("main.pdf")
    text = extractor.extract_from_file(path)
    assert "Reference PDF content." in text


def test_extract_from_file_pdf_read_error_returns_none(tmp_path: Path) -> None:
    """A corrupted reference .pdf returns None with a warning instead of raising."""
    path = tmp_path / "corrupt_ref.pdf"
    path.write_bytes(b"%PDF-1.4 garbage")
    extractor = TextExtractor("main.pdf")
    assert extractor.extract_from_file(path) is None


def test_extract_from_file_txt(make_txt: Callable[[str, str], Path]) -> None:
    """extract_from_file reads a reference .txt file in full via _extract_from_txt."""
    path = make_txt("ref.txt", "Reference text content.")
    extractor = TextExtractor("main.txt")
    text = extractor.extract_from_file(path)
    assert text == "Reference text content."


def test_extract_from_file_unsupported_extension_returns_none(tmp_path: Path) -> None:
    """An unsupported reference file extension returns None with a warning."""
    path = tmp_path / "ref.xyz"
    path.write_text("content")
    extractor = TextExtractor("main.txt")
    assert extractor.extract_from_file(path) is None
