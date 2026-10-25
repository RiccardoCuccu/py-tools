"""Tests for report: renderers, default path and write_report."""

import csv
import io
import json
from datetime import datetime

import pytest

import report
from utils import UnlistedVideo


def _videos() -> list[UnlistedVideo]:
    return [
        UnlistedVideo("a1", "Café [live]", "Chan A", "https://y/a1", ["P1", "P2"]),
        UnlistedVideo("b2", "Second", "Chan B", "https://y/b2", ["P2"]),
    ]


def test_default_path_uses_reports_dir_and_timestamp(paths):
    path = report.default_report_path("csv", datetime(2026, 3, 5, 14, 7))
    assert path == str(paths.reports_dir / "unlisted_2026-03-05_1407.csv")


def test_markdown_groups_by_playlist_and_repeats_shared_videos():
    text = report.render_markdown(_videos())
    assert text.index("## P1") < text.index("## P2")
    assert text.count("https://y/a1") == 2
    assert "- [Second](https://y/b2) - Chan B" in text


def test_markdown_escapes_brackets_in_titles():
    text = report.render_markdown(_videos())
    assert "[Café \\[live\\]](https://y/a1) - Chan A" in text


def test_markdown_empty_message():
    assert "No unlisted videos found." in report.render_markdown([])


def test_csv_has_one_row_per_video_with_joined_playlists():
    rows = list(csv.reader(io.StringIO(report.render_csv(_videos()))))
    assert rows[0] == ["title", "channel", "url", "video_id", "playlists"]
    assert len(rows) == 3
    assert rows[1][4] == "P1; P2"


def test_json_is_a_list_of_video_objects():
    data = json.loads(report.render_json(_videos()))
    assert [v["video_id"] for v in data] == ["a1", "b2"]
    assert data[0]["playlists"] == ["P1", "P2"]
    assert "Café" in report.render_json(_videos())


@pytest.mark.parametrize("fmt", ["md", "csv", "json"])
def test_write_report_creates_file(tmp_path, fmt):
    target = tmp_path / "out" / f"r.{fmt}"
    report.write_report(_videos(), fmt, str(target))
    assert target.exists()


def test_write_csv_has_bom_so_excel_reads_accents(tmp_path):
    target = tmp_path / "r.csv"
    report.write_report(_videos(), "csv", str(target))
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "Café".encode("utf-8") in raw


def test_write_report_rejects_unknown_format(tmp_path):
    with pytest.raises(ValueError):
        report.write_report([], "xml", str(tmp_path / "r.xml"))


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_neutralizes_formula_cells(prefix):
    video = UnlistedVideo("id", prefix + "cmd", prefix + "chan", "u", [prefix + "pl"])
    rows = list(csv.reader(io.StringIO(report.render_csv([video]))))
    assert rows[1][0] == "'" + prefix + "cmd"
    assert rows[1][1] == "'" + prefix + "chan"
    assert rows[1][4] == "'" + prefix + "pl"


def test_csv_leaves_normal_cells_untouched():
    video = UnlistedVideo("id", "Plain title", "Chan", "https://y/id", ["P"])
    rows = list(csv.reader(io.StringIO(report.render_csv([video]))))
    assert rows[1] == ["Plain title", "Chan", "https://y/id", "id", "P"]


def test_markdown_collapses_whitespace_and_newlines():
    video = UnlistedVideo("i", "Line one\nline   two\t!", "C", "https://y/i", ["P"])
    text = report.render_markdown([video])
    assert "[Line one line two !](https://y/i)" in text


def test_markdown_escapes_parentheses_backslashes_channel_and_playlist():
    bs = chr(92)
    video = UnlistedVideo(
        "i", f"A (b) {bs} c [d]", "Chan (x) [y]", "https://y/i", ["List [1] (2)"]
    )
    text = report.render_markdown([video])
    assert f"## List {bs}[1{bs}] {bs}(2{bs})" in text
    expected_title = f"A {bs}(b{bs}) {bs}{bs} c {bs}[d{bs}]"
    expected_channel = f"Chan {bs}(x{bs}) {bs}[y{bs}]"
    assert f"[{expected_title}](https://y/i) - {expected_channel}" in text
