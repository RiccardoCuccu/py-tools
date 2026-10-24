"""Tests for cleanup_util: the cache removal is anchored to the tool, not the working directory."""

import os
from pathlib import Path

import pytest

import cleanup_util as cu


def test_cache_dir_is_anchored_next_to_the_module() -> None:
    """CACHE_DIR is an absolute path beside cleanup_util.py, independent of the cwd."""
    expected = Path(cu.__file__).resolve().parent / "__pycache__"
    assert Path(cu.CACHE_DIR).resolve() == expected


def test_cleanup_removes_the_cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The configured cache directory and its content are deleted."""
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"x")
    monkeypatch.setattr(cu, "CACHE_DIR", str(cache))

    cu.cleanup()

    assert not cache.exists()


def test_cleanup_leaves_other_cwd_cache_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A __pycache__ in the working directory (another project) is never touched."""
    other = tmp_path / "other_project"
    (other / "__pycache__").mkdir(parents=True)
    own = tmp_path / "own"
    own.mkdir()
    monkeypatch.chdir(other)
    monkeypatch.setattr(cu, "CACHE_DIR", str(own / "__pycache__"))

    cu.cleanup()

    assert (other / "__pycache__").is_dir()


def test_cleanup_missing_cache_is_a_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No cache directory means nothing to do and no error."""
    monkeypatch.setattr(cu, "CACHE_DIR", str(tmp_path / "absent"))
    cu.cleanup()


def test_cleanup_reports_failures_on_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A deletion error is reported on stderr and not raised."""
    cache = tmp_path / "__pycache__"
    cache.mkdir()

    def boom(path: str) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(cu, "CACHE_DIR", str(cache))
    monkeypatch.setattr(cu.shutil, "rmtree", boom)

    cu.cleanup()

    assert "Error deleting cache directory" in capsys.readouterr().err
    assert os.path.isdir(cache)
