"""Tests for utils: atomic_write_text, Logger, UnlistedVideo."""

import pytest

import utils
from utils import Logger, UnlistedVideo, atomic_write_text


def test_atomic_write_creates_parents_and_leaves_no_temp(tmp_path):
    target = tmp_path / "a" / "b" / "out.txt"
    atomic_write_text(str(target), "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert list(target.parent.iterdir()) == [target]


def test_atomic_write_keeps_line_endings(tmp_path):
    target = tmp_path / "out.txt"
    atomic_write_text(str(target), "a\nb\r\n")
    assert target.read_bytes() == b"a\nb\r\n"


def test_atomic_write_honours_encoding(tmp_path):
    target = tmp_path / "out.csv"
    atomic_write_text(str(target), "x", encoding="utf-8-sig")
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")


def test_logger_warning_and_error_reach_console_and_file(paths, capsys):
    logger = Logger()
    logger.log_warning("careful")
    logger.log_error("broken")
    out = capsys.readouterr().out
    assert "WARNING: careful" in out and "ERROR: broken" in out
    content = paths.log_file.read_text(encoding="utf-8")
    assert "WARNING: careful" in content and "ERROR: broken" in content


def test_logger_info_is_not_written_to_file(paths, capsys):
    Logger().log_info("just info")
    assert capsys.readouterr().out == "just info\n"
    assert not paths.log_file.exists()


def test_unlisted_video_playlists_default_is_independent():
    first = UnlistedVideo("a", "t", "c", "u")
    second = UnlistedVideo("b", "t", "c", "u")
    first.playlists.append("x")
    assert second.playlists == []


def test_atomic_write_removes_temp_file_when_write_fails(tmp_path):
    folder = tmp_path / "out_dir"
    folder.mkdir()
    target = folder / "out.txt"
    # A lone surrogate cannot be encoded, so the write fails after the open
    with pytest.raises(UnicodeEncodeError):
        atomic_write_text(str(target), "\ud800")
    assert list(folder.iterdir()) == []


def test_atomic_write_removes_temp_file_when_replace_fails(tmp_path, monkeypatch):
    folder = tmp_path / "out_dir"
    folder.mkdir()
    target = folder / "out.txt"

    def fail(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(utils.os, "replace", fail)
    with pytest.raises(OSError):
        atomic_write_text(str(target), "data")
    assert list(folder.iterdir()) == []
