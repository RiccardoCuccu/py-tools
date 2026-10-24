"""Tests for merge_python_files: file collection order, merged output format, output
file safety, error paths, and the interactive main() entry point.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import merge_python_files as mpf


def write(path: Path, text: str) -> Path:
    """Create a UTF-8 text file (LF line endings) and return its path."""
    path.write_bytes(text.encode("utf-8"))
    return path


class TestCollectPythonFiles:
    def test_only_py_files_sorted_and_main_separated(self, tmp_path):
        write(tmp_path / "zeta.py", "z")
        write(tmp_path / "Alpha.py", "a")
        write(tmp_path / "main.py", "m")
        write(tmp_path / "notes.txt", "n")
        write(tmp_path / "beta.pyc", "b")
        (tmp_path / "pkg.py").mkdir()  # a directory named like a module
        others, main_file = mpf.collect_python_files(tmp_path)
        assert [p.name for p in others] == ["Alpha.py", "zeta.py"]
        assert main_file == tmp_path / "main.py"

    def test_no_main(self, tmp_path):
        write(tmp_path / "a.py", "a")
        _, main_file = mpf.collect_python_files(tmp_path)
        assert main_file is None

    def test_subfolders_are_not_scanned(self, tmp_path):
        (tmp_path / "sub").mkdir()
        write(tmp_path / "sub" / "hidden.py", "h")
        others, main_file = mpf.collect_python_files(tmp_path)
        assert others == [] and main_file is None


class TestMerge:
    def test_main_is_last_and_headers_present(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        write(src / "b.py", "B = 2\n")
        write(src / "main.py", "print(B)\n")
        write(src / "a.py", "A = 1\n")
        out = tmp_path / "out" / "merged.py"
        out.parent.mkdir()

        result = mpf.merge_python_files(src, out)

        assert result == out.resolve()
        text = out.read_text(encoding="utf-8")
        assert text == (
            "# File: a.py\nA = 1\n\n\n"
            "# File: b.py\nB = 2\n\n\n"
            "# File: main.py\nprint(B)\n\n"
        )

    def test_empty_folder_produces_empty_output(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        out = tmp_path / "merged.py"
        mpf.merge_python_files(src, out)
        assert out.read_text(encoding="utf-8") == ""

    def test_non_ascii_content_survives(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        write(src / "a.py", 'NAME = "caffè"\n')
        out = tmp_path / "merged.py"
        mpf.merge_python_files(src, out)
        assert "caffè" in out.read_text(encoding="utf-8")

    def test_bom_is_not_copied_into_output(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_bytes(b"\xef\xbb\xbfA = 1\n")
        (src / "b.py").write_bytes(b"\xef\xbb\xbfB = 2\n")
        out = tmp_path / "merged.py"
        mpf.merge_python_files(src, out)
        assert "﻿" not in out.read_text(encoding="utf-8")

    def test_output_is_deterministic(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        for name in ("c", "a", "b"):
            write(src / f"{name}.py", f"{name}\n")
        first = tmp_path / "one.py"
        second = tmp_path / "two.py"
        mpf.merge_python_files(src, first)
        mpf.merge_python_files(src, second)
        assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


class TestOutputSafety:
    def test_rerun_into_same_folder_does_not_merge_previous_output(self, tmp_path):
        write(tmp_path / "a.py", "A = 1\n")
        out = tmp_path / "merged.py"
        mpf.merge_python_files(tmp_path, out)
        first = out.read_text(encoding="utf-8")
        mpf.merge_python_files(tmp_path, out)
        assert out.read_text(encoding="utf-8") == first
        assert first.count("# File: merged.py") == 0

    def test_output_naming_a_real_source_is_refused_and_source_kept(self, tmp_path):
        source = write(tmp_path / "a.py", "A = 1\n")
        write(tmp_path / "b.py", "B = 2\n")
        with pytest.raises(FileExistsError):
            mpf.merge_python_files(tmp_path, source)
        assert source.read_text(encoding="utf-8") == "A = 1\n"

    def test_output_naming_main_is_refused(self, tmp_path):
        main_file = write(tmp_path / "main.py", "print(1)\n")
        with pytest.raises(FileExistsError):
            mpf.merge_python_files(tmp_path, main_file)
        assert main_file.read_text(encoding="utf-8") == "print(1)\n"

    def test_undecodable_source_leaves_existing_output_untouched(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        write(src / "a.py", "A = 1\n")
        (src / "b.py").write_bytes(b"\xff\xfe\x00bad")
        out = write(tmp_path / "merged.txt", "previous content")
        with pytest.raises(UnicodeDecodeError):
            mpf.merge_python_files(src, out)
        assert out.read_text(encoding="utf-8") == "previous content"


class TestErrors:
    def test_missing_folder_raises(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            mpf.merge_python_files(tmp_path / "nope", tmp_path / "out.py")

    def test_file_instead_of_folder_raises(self, tmp_path):
        file_path = write(tmp_path / "x.py", "x")
        with pytest.raises(NotADirectoryError):
            mpf.merge_python_files(file_path, tmp_path / "out.py")


class TestMain:
    def _answers(self, monkeypatch, *answers):
        it = iter(answers)
        monkeypatch.setattr("builtins.input", lambda _prompt: next(it))

    def test_success_returns_zero(self, tmp_path, monkeypatch, capsys):
        src = tmp_path / "src"
        src.mkdir()
        write(src / "a.py", "A = 1\n")
        out = tmp_path / "merged.py"
        self._answers(monkeypatch, f'  "{src}"  ', str(out))
        assert mpf.main() == 0
        assert out.exists()
        assert "Merging completed" in capsys.readouterr().out

    def test_error_returns_one_and_reports(self, tmp_path, monkeypatch, capsys):
        self._answers(monkeypatch, str(tmp_path / "nope"), str(tmp_path / "o.py"))
        assert mpf.main() == 1
        assert "ERROR" in capsys.readouterr().out
