"""Tests for find_duplicates: file collection, hashing, duplicate grouping, keeper
selection, deletion safety, and the main() entry point.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import find_duplicates as fd


def make_file(path: Path, data: bytes, mtime: float | None = None) -> Path:
    """Create a file with the given content and optional creation/modification time."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture(autouse=True)
def _same_creation_time_as_mtime(monkeypatch):
    """Make the creation time follow mtime so tests control which copy is oldest."""
    monkeypatch.setattr(fd, "_creation_time", lambda p: p.stat().st_mtime)


class TestCollectFiles:
    def test_non_recursive_ignores_subfolders(self, tmp_path):
        top = make_file(tmp_path / "a.txt", b"a")
        make_file(tmp_path / "sub" / "b.txt", b"b")
        assert fd.collect_files(tmp_path, recursive=False) == [top]

    def test_recursive_includes_subfolders(self, tmp_path):
        top = make_file(tmp_path / "a.txt", b"a")
        nested = make_file(tmp_path / "sub" / "deep" / "b.txt", b"b")
        assert fd.collect_files(tmp_path, recursive=True) == sorted([top, nested])

    def test_directories_are_not_returned(self, tmp_path):
        (tmp_path / "empty_dir").mkdir()
        assert fd.collect_files(tmp_path, recursive=True) == []

    def test_symlinks_are_skipped(self, tmp_path):
        target = make_file(tmp_path / "real.txt", b"data")
        link = tmp_path / "link.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not permitted on this system")
        assert fd.collect_files(tmp_path, recursive=False) == [target]
        assert fd.collect_files(tmp_path, recursive=True) == [target]


class TestHashing:
    def test_sha256_matches_hashlib(self, tmp_path):
        data = os.urandom(200_000)
        path = make_file(tmp_path / "f.bin", data)
        assert fd._sha256(path) == hashlib.sha256(data).hexdigest()

    def test_sha256_empty_file(self, tmp_path):
        path = make_file(tmp_path / "empty", b"")
        assert fd._sha256(path) == hashlib.sha256(b"").hexdigest()

    def test_small_chunk_size_gives_same_digest(self, tmp_path):
        path = make_file(tmp_path / "f", b"abcdefghij" * 10)
        assert fd._sha256(path, chunk_size=3) == fd._sha256(path)


class TestBuildHashMap:
    def test_groups_identical_content_regardless_of_name(self, tmp_path):
        a = make_file(tmp_path / "a.txt", b"same")
        b = make_file(tmp_path / "other_name.dat", b"same")
        make_file(tmp_path / "c.txt", b"different")
        result = fd.build_hash_map(fd.collect_files(tmp_path, recursive=False))
        assert len(result) == 1
        (paths,) = result.values()
        assert sorted(paths) == sorted([a, b])

    def test_no_duplicates_returns_empty(self, tmp_path):
        make_file(tmp_path / "a", b"1")
        make_file(tmp_path / "b", b"2")
        assert fd.build_hash_map(fd.collect_files(tmp_path, recursive=False)) == {}

    def test_same_size_different_content_not_grouped(self, tmp_path):
        make_file(tmp_path / "a", b"abcd")
        make_file(tmp_path / "b", b"abce")
        assert fd.build_hash_map(fd.collect_files(tmp_path, recursive=False)) == {}

    def test_unreadable_file_is_logged_and_skipped(self, tmp_path, caplog):
        a = make_file(tmp_path / "a", b"x")
        b = make_file(tmp_path / "b", b"x")
        missing = tmp_path / "gone"
        with caplog.at_level("WARNING"):
            result = fd.build_hash_map([a, b, missing])
        assert "Could not read" in caplog.text
        assert list(result.values()) == [[a, b]]


class TestResolveDuplicateGroup:
    def test_oldest_is_kept(self, tmp_path):
        new = make_file(tmp_path / "new", b"x", mtime=2_000_000_000)
        old = make_file(tmp_path / "old", b"x", mtime=1_000_000_000)
        mid = make_file(tmp_path / "mid", b"x", mtime=1_500_000_000)
        keeper, dups = fd.resolve_duplicate_group([new, old, mid])
        assert keeper == old
        assert dups == [mid, new]

    def test_tie_is_broken_by_path_deterministically(self, tmp_path):
        b = make_file(tmp_path / "b", b"x", mtime=1_000_000_000)
        a = make_file(tmp_path / "a", b"x", mtime=1_000_000_000)
        assert fd.resolve_duplicate_group([b, a])[0] == a
        assert fd.resolve_duplicate_group([a, b])[0] == a


class TestFormatSize:
    @pytest.mark.parametrize(
        ("size", "expected"),
        [
            (0, "0.0 B"),
            (1023, "1023.0 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (5 * 1024**2, "5.0 MB"),
            (3 * 1024**3, "3.0 GB"),
            (2 * 1024**4, "2.0 TB"),
        ],
    )
    def test_units(self, size, expected):
        assert fd._format_size(size) == expected


class TestAsk:
    @pytest.mark.parametrize(("answer", "expected"), [("y", True), ("YES", True), ("n", False), ("", False)])
    def test_answers(self, monkeypatch, answer, expected):
        monkeypatch.setattr("builtins.input", lambda _prompt: answer)
        assert fd._ask("?") is expected

    def test_reprompts_on_garbage(self, monkeypatch):
        answers = iter(["maybe", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
        assert fd._ask("?") is True

    def test_eof_means_no(self, monkeypatch):
        def raise_eof(_prompt):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        assert fd._ask("?") is False


def _hash_map(*paths: Path) -> dict[str, list[Path]]:
    return {"ab" * 32: list(paths)}


class TestProcessDuplicates:
    def test_auto_yes_deletes_newer_copies_only(self, tmp_path):
        old = make_file(tmp_path / "old", b"x", mtime=1_000_000_000)
        new = make_file(tmp_path / "new", b"x", mtime=2_000_000_000)
        deleted, skipped = fd.process_duplicates(
            _hash_map(old, new), dry_run=False, auto_yes=True
        )
        assert (deleted, skipped) == (1, 0)
        assert old.exists()
        assert not new.exists()

    def test_dry_run_deletes_nothing(self, tmp_path):
        old = make_file(tmp_path / "old", b"x", mtime=1_000_000_000)
        new = make_file(tmp_path / "new", b"x", mtime=2_000_000_000)
        deleted, skipped = fd.process_duplicates(
            _hash_map(old, new), dry_run=True, auto_yes=True
        )
        assert (deleted, skipped) == (0, 1)
        assert old.exists() and new.exists()

    def test_declined_prompt_keeps_file(self, tmp_path, monkeypatch):
        old = make_file(tmp_path / "old", b"x", mtime=1_000_000_000)
        new = make_file(tmp_path / "new", b"x", mtime=2_000_000_000)
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")
        deleted, skipped = fd.process_duplicates(
            _hash_map(old, new), dry_run=False, auto_yes=False
        )
        assert (deleted, skipped) == (0, 1)
        assert new.exists()

    def test_three_copies_leave_exactly_the_oldest(self, tmp_path):
        paths = [
            make_file(tmp_path / f"f{i}", b"x", mtime=1_000_000_000 + i) for i in range(3)
        ]
        deleted, _ = fd.process_duplicates(
            _hash_map(*reversed(paths)), dry_run=False, auto_yes=True
        )
        assert deleted == 2
        assert [p.exists() for p in paths] == [True, False, False]

    def test_missing_keeper_blocks_deletion(self, tmp_path, monkeypatch):
        old = make_file(tmp_path / "old", b"x", mtime=1_000_000_000)
        new = make_file(tmp_path / "new", b"x", mtime=2_000_000_000)
        # Keeper disappears after the group was resolved
        monkeypatch.setattr(fd, "_format_info", lambda p: (old.unlink(missing_ok=True), "")[1])
        deleted, skipped = fd.process_duplicates(
            _hash_map(old, new), dry_run=False, auto_yes=True
        )
        assert deleted == 0
        assert new.exists()

    def test_vanished_file_in_group_does_not_crash(self, tmp_path):
        old = make_file(tmp_path / "old", b"x", mtime=1_000_000_000)
        ghost = tmp_path / "ghost"
        deleted, skipped = fd.process_duplicates(
            _hash_map(old, ghost), dry_run=False, auto_yes=True
        )
        assert deleted == 0
        assert skipped == 1
        assert old.exists()

    def test_unlink_failure_is_counted_as_skipped(self, tmp_path, monkeypatch):
        old = make_file(tmp_path / "old", b"x", mtime=1_000_000_000)
        new = make_file(tmp_path / "new", b"x", mtime=2_000_000_000)

        def failing_unlink(self, *args, **kwargs):
            raise PermissionError("locked")

        monkeypatch.setattr(Path, "unlink", failing_unlink)
        deleted, skipped = fd.process_duplicates(
            _hash_map(old, new), dry_run=False, auto_yes=True
        )
        assert (deleted, skipped) == (0, 1)


class TestMain:
    def test_missing_source_returns_error(self, tmp_path):
        assert fd.main([str(tmp_path / "nope")]) == 1

    def test_empty_folder_returns_zero(self, tmp_path):
        assert fd.main([str(tmp_path)]) == 0

    def test_dry_run_leaves_everything(self, tmp_path):
        a = make_file(tmp_path / "a", b"x", mtime=1_000_000_000)
        b = make_file(tmp_path / "b", b"x", mtime=2_000_000_000)
        assert fd.main([str(tmp_path), "--dry-run"]) == 0
        assert a.exists() and b.exists()

    def test_yes_removes_duplicates_in_subfolders_when_recursive(self, tmp_path):
        old = make_file(tmp_path / "a", b"x", mtime=1_000_000_000)
        new = make_file(tmp_path / "sub" / "b", b"x", mtime=2_000_000_000)
        assert fd.main([str(tmp_path), "--yes"]) == 0
        assert new.exists()  # not scanned without --recursive
        assert fd.main([str(tmp_path), "--yes", "--recursive"]) == 0
        assert old.exists()
        assert not new.exists()

    def test_global_decline_aborts_without_deleting(self, tmp_path, monkeypatch):
        a = make_file(tmp_path / "a", b"x", mtime=1_000_000_000)
        b = make_file(tmp_path / "b", b"x", mtime=2_000_000_000)
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")
        assert fd.main([str(tmp_path)]) == 0
        assert a.exists() and b.exists()

    def test_unique_files_are_never_deleted(self, tmp_path):
        files = [make_file(tmp_path / f"f{i}", bytes([i])) for i in range(5)]
        assert fd.main([str(tmp_path), "--yes"]) == 0
        assert all(f.exists() for f in files)
