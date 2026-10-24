"""Tests for utils.py: storage, merging, logging and file removal."""

import json
from types import SimpleNamespace

import pytest

import utils
from utils import StorageManager, Logger, atomic_write_json, merge_videos, safe_remove_files


@pytest.fixture
def storage():
    return StorageManager(SimpleNamespace())


def video(video_id, published="2024-01-01T00:00:00Z"):
    return {"id": video_id, "title": video_id, "published": published, "url": video_id}


def test_merge_videos_appends_only_new_ids_in_order():
    merged = merge_videos([video("a"), video("b")], [video("b"), video("c"), video("c")])
    assert [v["id"] for v in merged] == ["a", "b", "c"]


def test_merge_videos_does_not_mutate_inputs():
    existing = [video("a")]
    merge_videos(existing, [video("b")])
    assert len(existing) == 1


def test_atomic_write_json_replaces_file_and_leaves_no_temp(tmp_path):
    target = tmp_path / "data.json"
    target.write_text("{}", encoding="utf-8")
    atomic_write_json(str(target), {"k": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 1}
    assert [p.name for p in tmp_path.glob("data.json*")] == ["data.json"]


def test_archive_roundtrip_ignores_blank_lines(storage, paths):
    storage.save_to_archive("a")
    storage.save_to_archive("b")
    with open(paths.archive_file, "a", encoding="utf-8") as f:
        f.write("\n  \n")
    assert storage.load_archive() == {"a", "b"}


def test_load_archive_missing_file_is_empty(storage):
    assert storage.load_archive() == set()


def test_default_state_has_no_quota_reset_date(storage):
    state = storage.load_state()
    assert state["full_backup_completed"] is False
    assert "quota_reset_date" not in state


def test_update_state_keeps_fields_written_by_others(storage):
    # A stale in-memory copy must never overwrite the quota counters on disk
    stale = storage.load_state()
    storage.save_state({**stale, "quota_used_today": 1650, "quota_reset_date": "2024-05-01"})
    updated = storage.update_state(total_videos_backed_up=3)
    assert updated["quota_used_today"] == 1650
    assert storage.load_state()["total_videos_backed_up"] == 3
    assert storage.load_state()["quota_reset_date"] == "2024-05-01"


def test_cache_roundtrip_and_clear(storage):
    storage.update_channel_videos_cache([video("a")], "UC1")
    assert storage.get_cached_videos("UC1") == [video("a")]
    assert storage.load_channel_videos()["total_count"] == 1
    storage.clear_channel_videos_cache()
    assert storage.get_cached_videos() == []


def test_cache_for_other_channel_is_ignored(storage):
    storage.update_channel_videos_cache([video("a")], "UC1")
    assert storage.get_cached_videos("UC2") == []
    assert storage.get_cached_videos() == [video("a")]


def test_logger_writes_error_and_backup_entries(paths, capsys):
    logger = Logger(SimpleNamespace())
    logger.log_error("boom")
    logger.log_warning("careful")
    logger.log_backed_up_video("src1", "Title", "Chan", "dst1")
    text = open(paths.log_file, encoding="utf-8").read()
    assert "ERROR: boom" in text
    assert "WARNING: careful" in text
    assert "watch?v=src1" in text and "watch?v=dst1" in text


def test_safe_remove_files_handles_none_and_missing(tmp_path):
    existing = tmp_path / "x.mp4"
    existing.write_bytes(b"1")
    safe_remove_files(str(existing), None, str(tmp_path / "missing.jpg"))
    assert not existing.exists()


def test_safe_remove_files_reports_oserror(tmp_path, monkeypatch, capsys):
    existing = tmp_path / "x.mp4"
    existing.write_bytes(b"1")

    def deny(self, *args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(utils.Path, "unlink", deny)
    safe_remove_files(str(existing))
    assert "locked" in capsys.readouterr().out
    assert existing.exists()
