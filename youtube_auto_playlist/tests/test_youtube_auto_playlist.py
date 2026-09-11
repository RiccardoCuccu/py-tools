"""Tests for youtube_auto_playlist: trim_processed_videos and load_state/save_state."""

import json
from pathlib import Path

import pytest

import youtube_auto_playlist
from youtube_auto_playlist import MAX_PROCESSED_VIDEOS, trim_processed_videos


@pytest.fixture
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module's STATE_FILE constant at a throwaway path under tmp_path."""
    path = tmp_path / "state.json"
    monkeypatch.setattr(youtube_auto_playlist, "STATE_FILE", str(path))
    return path


# --- trim_processed_videos ---


def test_new_ids_are_appended_without_duplication() -> None:
    """Distinct ids are all kept, with no duplication introduced."""
    result = trim_processed_videos(["a", "b", "c"])
    assert result == ["a", "b", "c"]


def test_duplicate_id_collapses_and_keeps_original_position() -> None:
    """An id seen twice collapses to a single entry at its FIRST occurrence position.

    This verifies dict.fromkeys' first-occurrence-wins semantics explicitly:
    the duplicate later in the sequence does not move the entry.
    """
    result = trim_processed_videos(["a", "b", "a", "c"])
    assert result == ["a", "b", "c"]


def test_insertion_order_is_preserved_end_to_end() -> None:
    """Order of first appearance is preserved through the whole pipeline."""
    ids = ["v3", "v1", "v2", "v1", "v3", "v4"]
    result = trim_processed_videos(ids)
    assert result == ["v3", "v1", "v2", "v4"]


def test_over_cap_keeps_only_the_most_recent_limit_entries() -> None:
    """When unique ids exceed the cap, only the newest `limit` entries survive."""
    ids = [f"id{i}" for i in range(10)]
    result = trim_processed_videos(ids, limit=4)
    assert result == ["id6", "id7", "id8", "id9"]
    assert len(result) == 4


def test_recently_added_id_survives_truncation() -> None:
    """Truncation always discards the oldest entries, never the newest one.

    `trim_processed_videos` must preserve insertion order rather than any
    hash-based ordering, so that a video id recorded in the very same batch
    is guaranteed to survive truncation while the oldest entries are the
    ones dropped.
    """
    old_ids = [f"old-{i}" for i in range(MAX_PROCESSED_VIDEOS)]
    fresh_id = "freshly-added-id"
    result = trim_processed_videos(old_ids + [fresh_id])

    assert fresh_id in result
    assert "old-0" not in result
    assert len(result) == MAX_PROCESSED_VIDEOS


def test_empty_input_returns_empty_list() -> None:
    """No ids in, no ids out."""
    assert trim_processed_videos([]) == []


def test_limit_zero_returns_empty_list() -> None:
    """A zero limit must return an empty list, not the full list.

    `some_list[-0:]` returns the WHOLE list because -0 == 0, so this case
    requires an explicit guard rather than relying on slice semantics.
    """
    assert trim_processed_videos(["a", "b", "c"], limit=0) == []


def test_negative_limit_returns_empty_list() -> None:
    """A negative limit is also treated as "keep nothing"."""
    assert trim_processed_videos(["a", "b", "c"], limit=-5) == []


def test_accepts_dict_input_and_reads_keys_in_insertion_order() -> None:
    """The `processed_videos` mapping in `run()` is a dict, not just a list.

    Iterating a dict yields its keys in insertion order, so trim_processed_videos
    must accept a dict directly and preserve that order.
    """
    source: dict[str, None] = {}
    source["b"] = None
    source["a"] = None
    source["c"] = None

    result = trim_processed_videos(source)

    assert result == ["b", "a", "c"]


# --- load_state / save_state ---


def test_missing_state_file_returns_defaults(state_file: Path) -> None:
    """When no state file exists yet, load_state returns the documented defaults."""
    state = youtube_auto_playlist.load_state()

    assert state["last_check_time"] is None
    assert state["processed_videos"] == []
    assert state["quota_used_today"] == 0
    assert "quota_reset_date" in state


def test_existing_state_file_loads_ids_in_file_order(state_file: Path) -> None:
    """An existing state file's processed_videos list loads verbatim, in file order.

    This is a backward-compatibility check against the live state file format,
    which already stores plain lists of ids.
    """
    ids_in_file_order = ["v3", "v1", "v2"]
    state_file.write_text(
        json.dumps(
            {
                "last_check_time": "2026-01-01T00:00:00+00:00",
                "processed_videos": ids_in_file_order,
                "quota_used_today": 42,
                "quota_reset_date": "2026-01-01",
            }
        ),
        encoding="utf-8",
    )

    state = youtube_auto_playlist.load_state()

    assert state["processed_videos"] == ids_in_file_order


def test_quota_fields_backfilled_when_absent(state_file: Path) -> None:
    """Older state files without quota fields get them backfilled on load."""
    state_file.write_text(
        json.dumps({"last_check_time": None, "processed_videos": []}),
        encoding="utf-8",
    )

    state = youtube_auto_playlist.load_state()

    assert state["quota_used_today"] == 0
    assert "quota_reset_date" in state


def test_save_then_load_round_trips_and_preserves_order(state_file: Path) -> None:
    """save_state followed by load_state returns an equivalent state, order intact."""
    ids_in_order = ["a", "c", "b", "d"]
    original_state = {
        "last_check_time": "2026-02-02T00:00:00+00:00",
        "processed_videos": ids_in_order,
        "quota_used_today": 7,
        "quota_reset_date": "2026-02-02",
    }

    youtube_auto_playlist.save_state(original_state)
    loaded_state = youtube_auto_playlist.load_state()

    assert loaded_state == original_state
    assert loaded_state["processed_videos"] == ids_in_order
