"""Tests for pdf_highlight_extractor: output path derivation, highlight extraction from
real (generated) PDFs, annotation filtering, and error paths. The Tk window is never
created; only the pure functions are exercised.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

import pdf_highlight_extractor as phe

LINE_HEIGHT = 20
FIRST_LINE_Y = 100


def build_pdf(path: Path, pages: list[list[str]], highlights=(), underlines=()) -> Path:
    """
    Create a PDF whose pages contain the given lines of text.

    highlights/underlines are (page_index, text) pairs; the first occurrence of
    the text on that page gets the annotation.
    """
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        for i, line in enumerate(lines):
            page.insert_text((72, FIRST_LINE_Y + i * LINE_HEIGHT), line, fontsize=12)
    for page_index, text in highlights:
        page = doc[page_index]
        page.add_highlight_annot(page.search_for(text))
    for page_index, text in underlines:
        page = doc[page_index]
        page.add_underline_annot(page.search_for(text))
    doc.save(str(path))
    doc.close()
    return path


class TestDefaultOutputPath:
    def test_replaces_only_final_extension(self):
        assert phe.default_output_path("C:/my.dir/paper.v2.pdf") == Path("C:/my.dir/paper.v2.txt")

    def test_dotted_folder_without_extension_keeps_folder(self):
        # Splitting on the last dot of the full path would have clobbered the folder
        assert phe.default_output_path("/data/my.dir/file") == Path("/data/my.dir/file.txt")

    def test_uppercase_extension(self):
        assert phe.default_output_path("/x/Doc.PDF") == Path("/x/Doc.txt")


class TestCollectHighlights:
    def test_extracts_highlighted_words_only(self, tmp_path):
        pdf = build_pdf(
            tmp_path / "a.pdf",
            [["alpha beta gamma", "delta epsilon"]],
            highlights=[(0, "beta")],
        )
        assert phe.collect_highlights(pdf) == ["beta"]

    def test_highlights_in_page_order(self, tmp_path):
        pdf = build_pdf(
            tmp_path / "a.pdf",
            [["first page words"], ["second page words"]],
            highlights=[(1, "second"), (0, "first")],
        )
        assert phe.collect_highlights(pdf) == ["first", "second"]

    def test_multi_word_highlight(self, tmp_path):
        pdf = build_pdf(
            tmp_path / "a.pdf",
            [["the quick brown fox jumps"]],
            highlights=[(0, "quick brown fox")],
        )
        assert phe.collect_highlights(pdf) == ["quick brown fox"]

    def test_non_highlight_annotations_are_ignored(self, tmp_path):
        pdf = build_pdf(
            tmp_path / "a.pdf",
            [["keep this", "underline that"]],
            highlights=[(0, "keep")],
            underlines=[(0, "underline")],
        )
        assert phe.collect_highlights(pdf) == ["keep"]

    def test_pdf_without_annotations_returns_empty(self, tmp_path):
        pdf = build_pdf(tmp_path / "a.pdf", [["plain text"]])
        assert phe.collect_highlights(pdf) == []

    def test_highlight_over_blank_area_is_skipped(self, tmp_path):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "some text", fontsize=12)
        page.add_highlight_annot(fitz.Rect(300, 600, 400, 620))
        pdf = tmp_path / "blank.pdf"
        doc.save(str(pdf))
        doc.close()
        assert phe.collect_highlights(pdf) == []

    def test_multi_line_highlight_is_joined_on_one_line(self, tmp_path):
        pdf = build_pdf(
            tmp_path / "a.pdf",
            [["line one here", "line two here"]],
        )
        doc = fitz.open(str(pdf))
        page = doc[0]
        rects = page.search_for("one here") + page.search_for("line two")
        page.add_highlight_annot(rects)
        multi = tmp_path / "multi.pdf"
        doc.save(str(multi))
        doc.close()
        result = phe.collect_highlights(multi)
        assert len(result) == 1
        assert "\n" not in result[0]
        assert "one here" in result[0] and "line two" in result[0]

    def test_password_protected_pdf_raises_value_error(self, tmp_path):
        plain = build_pdf(tmp_path / "plain.pdf", [["secret"]], highlights=[(0, "secret")])
        doc = fitz.open(str(plain))
        locked = tmp_path / "locked.pdf"
        doc.save(
            str(locked),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="pw",
            owner_pw="pw",
        )
        doc.close()
        with pytest.raises(ValueError, match="password"):
            phe.collect_highlights(locked)

    def test_non_pdf_file_raises_runtime_error(self, tmp_path):
        bogus = tmp_path / "bogus.pdf"
        bogus.write_bytes(b"this is not a pdf")
        with pytest.raises(RuntimeError):
            phe.collect_highlights(bogus)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises((RuntimeError, OSError)):
            phe.collect_highlights(tmp_path / "missing.pdf")


class TestQuadTexts:
    def test_incomplete_trailing_quad_is_ignored(self, tmp_path):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "hello world", fontsize=12)
        rect = page.search_for("hello")[0]
        quad = rect.quad
        points = [quad.ul, quad.ur, quad.ll, quad.lr]
        texts = phe._quad_texts(page, points + [fitz.Point(0, 0)])
        doc.close()
        assert texts == ["hello"]

    def test_empty_vertices_returns_empty(self):
        assert phe._quad_texts(None, []) == []


class TestExtractHighlightedText:
    def test_writes_paragraph_per_highlight_and_returns_count(self, tmp_path):
        pdf = build_pdf(
            tmp_path / "a.pdf",
            [["alpha beta gamma"]],
            highlights=[(0, "alpha"), (0, "gamma")],
        )
        out = tmp_path / "a.txt"
        assert phe.extract_highlighted_text(pdf, out) == 2
        assert out.read_text(encoding="utf-8") == "alpha\n\ngamma\n\n"

    def test_no_highlights_writes_empty_file(self, tmp_path):
        pdf = build_pdf(tmp_path / "a.pdf", [["nothing here"]])
        out = tmp_path / "a.txt"
        assert phe.extract_highlighted_text(pdf, out) == 0
        assert out.read_text(encoding="utf-8") == ""

    def test_unreadable_pdf_does_not_touch_existing_output(self, tmp_path):
        bogus = tmp_path / "bogus.pdf"
        bogus.write_bytes(b"not a pdf")
        out = tmp_path / "bogus.txt"
        out.write_text("precious notes", encoding="utf-8")
        with pytest.raises(RuntimeError):
            phe.extract_highlighted_text(bogus, out)
        assert out.read_text(encoding="utf-8") == "precious notes"
