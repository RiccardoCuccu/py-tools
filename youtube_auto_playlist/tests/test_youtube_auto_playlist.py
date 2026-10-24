"""Tests for youtube_auto_playlist: pure helpers, state, feeds, auth and run()."""

import json
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError

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


# --- helpers shared by the tests below ---

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>new1</yt:videoId>
    <title>Fresh video</title>
    <author><name>Chan</name></author>
    <published>2026-03-01T11:00:00+00:00</published>
  </entry>
  <entry>
    <yt:videoId>old1</yt:videoId>
    <title>Old video</title>
    <author><name>Chan</name></author>
    <published>2026-02-01T11:00:00+00:00</published>
  </entry>
  <entry>
    <yt:videoId>nodate</yt:videoId>
    <title>No date</title>
    <author><name>Chan</name></author>
  </entry>
  <entry>
    <yt:videoId>baddate</yt:videoId>
    <title>Bad date</title>
    <author><name>Chan</name></author>
    <published>not-a-date</published>
  </entry>
</feed>
""".encode("utf-8")

FEED_CUTOFF = datetime(2026, 2, 28, tzinfo=timezone.utc)


def video(video_id: str, title: str = "Title") -> dict:
    """Build a minimal video dict as produced by the fetch functions."""
    return {"video_id": video_id, "title": title, "channel_title": "Chan"}


class FakeResponse:
    """Context-manager stand-in for the object returned by urllib's urlopen."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def make_service(durations: dict[str, str] | None = None) -> MagicMock:
    """Build a fake YouTube service whose videos().list() reports the given durations."""
    service = MagicMock()
    items = [
        {"id": vid, "contentDetails": {"duration": dur}}
        for vid, dur in (durations or {}).items()
    ]
    service.videos.return_value.list.return_value.execute.return_value = {"items": items}
    return service


def serve_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make urlopen return the sample Atom feed."""
    monkeypatch.setattr(
        youtube_auto_playlist.urllib.request,
        "urlopen",
        lambda *a, **k: FakeResponse(ATOM_FEED),
    )


def fail_urlopen(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    """Make urlopen raise the given error."""

    def raiser(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(youtube_auto_playlist.urllib.request, "urlopen", raiser)


# --- write_text_atomic ---


def test_write_text_atomic_replaces_content_and_leaves_no_temp_file(tmp_path: Path) -> None:
    """The target holds the new text and no .tmp sibling remains."""
    target = tmp_path / "data.json"
    target.write_text("old", encoding="utf-8")

    youtube_auto_playlist.write_text_atomic(str(target), "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("data")] == ["data.json"]


def test_failed_atomic_write_keeps_previous_state(
    state_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the final replace fails, the previous state file is untouched."""
    youtube_auto_playlist.save_state({"processed_videos": ["keep"]})

    def boom(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(youtube_auto_playlist.os, "replace", boom)
    with pytest.raises(OSError):
        youtube_auto_playlist.save_state({"processed_videos": ["lost"]})

    assert json.loads(state_file.read_text(encoding="utf-8")) == {"processed_videos": ["keep"]}


# --- parse_duration ---


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("PT1M30S", 90),
        ("PT45S", 45),
        ("PT2H", 7200),
        ("PT1H2M3S", 3723),
        ("P1DT2H", 93600),
        ("P0D", 0),
        ("PT0S", 0),
        ("garbage", 0),
        ("", 0),
        (None, 0),
    ],
)
def test_parse_duration(text: str | None, seconds: int) -> None:
    """ISO 8601 durations convert to seconds; unparseable input yields zero."""
    assert youtube_auto_playlist.parse_duration(text) == seconds


# --- playlist id handling ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PLabc_-123", "PLabc_-123"),
        ("  PLabc  ", "PLabc"),
        ("https://www.youtube.com/playlist?list=PLabc_-123", "PLabc_-123"),
        ("https://www.youtube.com/watch?v=xyz&list=PLq9&index=2", "PLq9"),
        (None, ""),
    ],
)
def test_normalize_playlist_id(raw: str | None, expected: str) -> None:
    """A bare id or a pasted URL both resolve to the bare playlist id."""
    assert youtube_auto_playlist.normalize_playlist_id(raw) == expected


def test_get_target_playlist_id_returns_configured_id() -> None:
    """A configured id is returned."""
    config = {"youtube": {"target_playlist_id": "PL123"}}
    assert youtube_auto_playlist.get_target_playlist_id(config) == "PL123"


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"youtube": None},
        {"youtube": {}},
        {"youtube": {"target_playlist_id": "YOUR_PLAYLIST_ID_HERE"}},
    ],
)
def test_get_target_playlist_id_rejects_missing_or_placeholder(config: dict) -> None:
    """Missing sections and the placeholder id raise a clear ValueError."""
    with pytest.raises(ValueError):
        youtube_auto_playlist.get_target_playlist_id(config)


# --- keyword filter ---


def test_keyword_filter_disabled_accepts_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the filter off every title passes."""
    monkeypatch.setattr(youtube_auto_playlist, "ENABLE_KEYWORD_FILTER", False)
    monkeypatch.setattr(youtube_auto_playlist, "FILTER_KEYWORDS", ["x"])
    assert youtube_auto_playlist.matches_keyword_filter("anything")


def test_keyword_filter_include_mode_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Include mode needs at least one keyword, ignoring case."""
    monkeypatch.setattr(youtube_auto_playlist, "ENABLE_KEYWORD_FILTER", True)
    monkeypatch.setattr(youtube_auto_playlist, "FILTER_MODE", "include")
    monkeypatch.setattr(youtube_auto_playlist, "FILTER_KEYWORDS", ["Tutorial"])
    assert youtube_auto_playlist.matches_keyword_filter("A TUTORIAL on x")
    assert not youtube_auto_playlist.matches_keyword_filter("Vlog")


def test_keyword_filter_exclude_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exclude mode rejects titles containing any keyword."""
    monkeypatch.setattr(youtube_auto_playlist, "ENABLE_KEYWORD_FILTER", True)
    monkeypatch.setattr(youtube_auto_playlist, "FILTER_MODE", "exclude")
    monkeypatch.setattr(youtube_auto_playlist, "FILTER_KEYWORDS", ["spoiler"])
    assert not youtube_auto_playlist.matches_keyword_filter("Spoiler alert")
    assert youtube_auto_playlist.matches_keyword_filter("Review")


def test_keyword_filter_unknown_mode_accepts_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    """An invalid mode falls back to accepting every title."""
    monkeypatch.setattr(youtube_auto_playlist, "ENABLE_KEYWORD_FILTER", True)
    monkeypatch.setattr(youtube_auto_playlist, "FILTER_MODE", "bogus")
    monkeypatch.setattr(youtube_auto_playlist, "FILTER_KEYWORDS", ["x"])
    assert youtube_auto_playlist.matches_keyword_filter("whatever")


# --- parse_rss_feed ---


def test_parse_rss_feed_keeps_only_recent_valid_entries() -> None:
    """Old entries and entries with a missing or malformed date are skipped."""
    videos = youtube_auto_playlist.parse_rss_feed(ATOM_FEED, FEED_CUTOFF)

    assert [v["video_id"] for v in videos] == ["new1"]
    assert videos[0]["title"] == "Fresh video"
    assert videos[0]["channel_title"] == "Chan"


def test_parse_rss_feed_threshold_is_inclusive() -> None:
    """A video published exactly at the cutoff is included."""
    cutoff = datetime(2026, 3, 1, 11, 0, tzinfo=timezone.utc)
    videos = youtube_auto_playlist.parse_rss_feed(ATOM_FEED, cutoff)
    assert [v["video_id"] for v in videos] == ["new1"]


def test_parse_rss_feed_rejects_invalid_xml() -> None:
    """Malformed XML raises instead of silently returning no videos."""
    with pytest.raises(ET.ParseError):
        youtube_auto_playlist.parse_rss_feed(b"<feed><entry>", NOW)


# --- RSS fetching ---


def test_rss_fetch_returns_long_videos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Videos above the Shorts limit are kept and the duration lookup is charged."""
    monkeypatch.setattr(youtube_auto_playlist, "INCLUDE_SHORTS", False)
    serve_feed(monkeypatch)
    service = make_service({"new1": "PT10M"})

    videos = youtube_auto_playlist.get_recent_videos_from_channel_rss(service, "UC1", FEED_CUTOFF)

    assert [v["video_id"] for v in videos] == ["new1"]
    assert youtube_auto_playlist.quota_used == 1


def test_rss_fetch_drops_short_videos(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 30 second video is treated as a Short and removed."""
    monkeypatch.setattr(youtube_auto_playlist, "INCLUDE_SHORTS", False)
    serve_feed(monkeypatch)
    service = make_service({"new1": "PT30S"})

    videos = youtube_auto_playlist.get_recent_videos_from_channel_rss(service, "UC1", FEED_CUTOFF)

    assert videos == []


def test_rss_fetch_with_shorts_included_makes_no_api_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """With INCLUDE_SHORTS on, the feed alone decides and no quota is spent."""
    monkeypatch.setattr(youtube_auto_playlist, "INCLUDE_SHORTS", True)
    serve_feed(monkeypatch)
    service = make_service()

    videos = youtube_auto_playlist.get_recent_videos_from_channel_rss(service, "UC1", FEED_CUTOFF)

    assert len(videos) == 1
    service.videos.assert_not_called()
    assert youtube_auto_playlist.quota_used == 0


def test_rss_fetch_404_yields_no_videos(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing feed (terminated channel) is skipped rather than failing the run."""
    fail_urlopen(monkeypatch, urllib.error.HTTPError("u", 404, "Not Found", None, None))  # type: ignore[arg-type]

    assert youtube_auto_playlist.get_recent_videos_from_channel_rss(make_service(), "UC1", NOW) == []


def test_rss_fetch_network_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient network error must propagate so the timestamp is not advanced."""
    fail_urlopen(monkeypatch, urllib.error.URLError("offline"))

    with pytest.raises(urllib.error.URLError):
        youtube_auto_playlist.get_recent_videos_from_channel_rss(make_service(), "UC1", NOW)


def test_rss_fetch_server_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-404 HTTP errors also propagate."""
    fail_urlopen(monkeypatch, urllib.error.HTTPError("u", 500, "Boom", None, None))  # type: ignore[arg-type]

    with pytest.raises(urllib.error.HTTPError):
        youtube_auto_playlist.get_recent_videos_from_channel_rss(make_service(), "UC1", NOW)


# --- filter_out_shorts ---


def test_filter_out_shorts_keeps_only_videos_above_limit() -> None:
    """Only videos strictly longer than the limit survive; unknown ids are dropped."""
    service = make_service({"a": "PT3M", "b": "PT2M", "c": "PT10S"})
    videos = [video("a"), video("b"), video("c"), video("missing")]

    kept = youtube_auto_playlist.filter_out_shorts(service, videos)

    assert [v["video_id"] for v in kept] == ["a"]
    assert youtube_auto_playlist.quota_used == 1


def test_filter_out_shorts_with_no_videos_spends_no_quota() -> None:
    """An empty batch skips the API call entirely."""
    service = make_service()
    assert youtube_auto_playlist.filter_out_shorts(service, []) == []
    service.videos.assert_not_called()
    assert youtube_auto_playlist.quota_used == 0


# --- API search ---


def test_api_search_maps_items_and_charges_search_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    """Search results map to video dicts and cost the search quota."""
    monkeypatch.setattr(youtube_auto_playlist, "INCLUDE_SHORTS", True)
    service = MagicMock()
    service.search.return_value.list.return_value.execute.return_value = {
        "items": [{"id": {"videoId": "v1"}, "snippet": {"title": "T1", "channelTitle": "C1"}}]
    }

    videos = youtube_auto_playlist.get_recent_videos_from_channel(
        service, "UC1", "2026-03-01T00:00:00+00:00"
    )

    assert videos == [{"video_id": "v1", "title": "T1", "channel_title": "C1"}]
    assert youtube_auto_playlist.quota_used == youtube_auto_playlist.QUOTA_COST_SEARCH


# --- quota day rollover ---


def test_quota_resets_when_pacific_date_changes() -> None:
    """A stale reset date zeroes the counter and stamps today's Pacific date."""
    state = {"quota_used_today": 900, "quota_reset_date": "2000-01-01"}

    assert youtube_auto_playlist.reset_quota_if_new_day(state) is True

    assert state["quota_used_today"] == 0
    assert state["quota_reset_date"] != "2000-01-01"


def test_quota_kept_within_same_pacific_day() -> None:
    """The counter is untouched when the date matches."""
    today = datetime.now(youtube_auto_playlist.PACIFIC_TZ).date().isoformat()
    state = {"quota_used_today": 900, "quota_reset_date": today}

    assert youtube_auto_playlist.reset_quota_if_new_day(state) is False
    assert state["quota_used_today"] == 900


# --- subscriptions cache ---


def test_subscriptions_cache_round_trip() -> None:
    """A freshly saved cache loads back with its subscriptions."""
    subs = [{"channel_id": "UC1", "channel_title": "One"}]
    youtube_auto_playlist.save_subscriptions_cache(subs, etag="e")

    cache = youtube_auto_playlist.load_subscriptions_cache()

    assert cache is not None
    assert cache["subscriptions"] == subs


def test_expired_subscriptions_cache_is_ignored() -> None:
    """A cache older than the configured lifetime is discarded."""
    lifetime = timedelta(hours=youtube_auto_playlist.CACHE_SUBSCRIPTIONS_HOURS + 1)
    old = datetime.now(timezone.utc) - lifetime
    Path(youtube_auto_playlist.SUBSCRIPTIONS_CACHE_FILE).write_text(
        json.dumps({"cached_at": old.isoformat(), "subscriptions": []}), encoding="utf-8"
    )

    assert youtube_auto_playlist.load_subscriptions_cache() is None


@pytest.mark.parametrize(
    "content", ["{not json", "{}", '{"cached_at": "nope", "subscriptions": []}']
)
def test_corrupt_subscriptions_cache_is_ignored(content: str) -> None:
    """Unreadable or malformed cache files fall back to a fresh fetch."""
    Path(youtube_auto_playlist.SUBSCRIPTIONS_CACHE_FILE).write_text(content, encoding="utf-8")

    assert youtube_auto_playlist.load_subscriptions_cache() is None


def test_get_all_subscriptions_follows_pagination_and_caches() -> None:
    """All pages are fetched, quota is charged per page, and the result is cached."""
    service = MagicMock()
    page1 = {
        "etag": "E",
        "nextPageToken": "T2",
        "items": [{"snippet": {"resourceId": {"channelId": "UC1"}, "title": "One"}}],
    }
    page2 = {"items": [{"snippet": {"resourceId": {"channelId": "UC2"}, "title": "Two"}}]}
    service.subscriptions.return_value.list.return_value.execute.side_effect = [page1, page2]

    subs = youtube_auto_playlist.get_all_subscriptions(service)

    assert [s["channel_id"] for s in subs] == ["UC1", "UC2"]
    assert youtube_auto_playlist.quota_used == 2
    assert youtube_auto_playlist.load_subscriptions_cache() is not None


# --- add_video_to_playlist ---


def test_add_video_dry_run_makes_no_api_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry run reports success without touching the API or quota."""
    monkeypatch.setattr(youtube_auto_playlist, "DRY_RUN", True)
    service = MagicMock()

    assert youtube_auto_playlist.add_video_to_playlist(service, "PL", "v1") is True
    service.playlistItems.assert_not_called()
    assert youtube_auto_playlist.quota_used == 0


def test_add_video_success_charges_insert_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real insert posts the right body and charges the insert cost."""
    monkeypatch.setattr(youtube_auto_playlist, "DRY_RUN", False)
    service = MagicMock()

    assert youtube_auto_playlist.add_video_to_playlist(service, "PL", "v1") is True

    body = service.playlistItems.return_value.insert.call_args.kwargs["body"]
    assert body["snippet"]["playlistId"] == "PL"
    assert body["snippet"]["resourceId"]["videoId"] == "v1"
    assert youtube_auto_playlist.quota_used == youtube_auto_playlist.QUOTA_COST_PLAYLIST_INSERT


def test_add_video_failure_returns_false_without_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    """An API failure is reported as False and no quota is charged."""
    monkeypatch.setattr(youtube_auto_playlist, "DRY_RUN", False)
    service = MagicMock()
    service.playlistItems.return_value.insert.return_value.execute.side_effect = RuntimeError("x")

    assert youtube_auto_playlist.add_video_to_playlist(service, "PL", "v1") is False
    assert youtube_auto_playlist.quota_used == 0


# --- log_added_video ---


def test_log_added_video_appends_a_line() -> None:
    """Each call appends one line with channel, title and URL."""
    youtube_auto_playlist.log_added_video("v1", "First", "Chan")
    youtube_auto_playlist.log_added_video("v2", "Second", "Chan")

    lines = Path(youtube_auto_playlist.LOG_FILE).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("Chan - First - https://www.youtube.com/watch?v=v1")


# --- run(): state handling end to end ---


@pytest.fixture
def run_env(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub authentication, config and subscriptions so run() touches only tmp_path."""
    service = MagicMock()
    Path(youtube_auto_playlist.CONFIG_FILE).write_text(
        "youtube:\n  target_playlist_id: PL1\n", encoding="utf-8"
    )
    monkeypatch.setattr(youtube_auto_playlist, "authenticate", lambda: service)
    monkeypatch.setattr(
        youtube_auto_playlist,
        "get_all_subscriptions",
        lambda svc: [{"channel_id": "UC1", "channel_title": "Chan"}],
    )
    monkeypatch.setattr(youtube_auto_playlist, "USE_RSS_FEEDS", True)
    monkeypatch.setattr(youtube_auto_playlist, "DRY_RUN", False)
    return service


def stub_fetch(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    """Make the RSS fetch return a list, or raise when given an exception."""

    def fake(*args: object, **kwargs: object) -> list:
        if isinstance(result, Exception):
            raise result
        return result  # type: ignore[return-value]

    monkeypatch.setattr(youtube_auto_playlist, "get_recent_videos_from_channel_rss", fake)


def test_run_adds_video_records_state_and_advances_timestamp(
    run_env: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful cycle logs the video, remembers its id and moves the cutoff."""
    stub_fetch(monkeypatch, [video("v1", "Hello")])

    youtube_auto_playlist.run()

    state = youtube_auto_playlist.load_state()
    assert state["processed_videos"] == ["v1"]
    assert state["last_check_time"] is not None
    assert state["quota_used_today"] == youtube_auto_playlist.QUOTA_COST_PLAYLIST_INSERT
    assert "v1" in Path(youtube_auto_playlist.LOG_FILE).read_text(encoding="utf-8")


def test_run_does_not_re_add_already_processed_video(
    run_env: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A video id already in state is skipped."""
    today = datetime.now(youtube_auto_playlist.PACIFIC_TZ).date().isoformat()
    youtube_auto_playlist.save_state(
        {
            "last_check_time": None,
            "processed_videos": ["v1"],
            "quota_used_today": 0,
            "quota_reset_date": today,
        }
    )
    stub_fetch(monkeypatch, [video("v1")])

    youtube_auto_playlist.run()

    run_env.playlistItems.assert_not_called()


def test_run_keeps_timestamp_when_a_channel_fetch_fails(
    run_env: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fetch error must leave last_check_time unset so the window is retried."""
    stub_fetch(monkeypatch, RuntimeError("network down"))

    youtube_auto_playlist.run()

    assert youtube_auto_playlist.load_state()["last_check_time"] is None


def test_run_keeps_timestamp_when_playlist_insert_fails(
    run_env: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed insert keeps the window open and does not mark the video processed."""
    stub_fetch(monkeypatch, [video("v1")])
    run_env.playlistItems.return_value.insert.return_value.execute.side_effect = RuntimeError("403")

    youtube_auto_playlist.run()

    state = youtube_auto_playlist.load_state()
    assert state["last_check_time"] is None
    assert state["processed_videos"] == []


def test_run_dry_run_records_nothing(run_env: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry run neither logs, nor marks videos processed, nor advances the cutoff."""
    monkeypatch.setattr(youtube_auto_playlist, "DRY_RUN", True)
    stub_fetch(monkeypatch, [video("v1")])

    youtube_auto_playlist.run()

    state = youtube_auto_playlist.load_state()
    assert state["processed_videos"] == []
    assert state["last_check_time"] is None
    run_env.playlistItems.assert_not_called()
    assert not Path(youtube_auto_playlist.LOG_FILE).exists()


def test_run_saves_processed_ids_when_interrupted(
    run_env: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ctrl+C after one video was added still persists that id, but not the cutoff."""
    monkeypatch.setattr(
        youtube_auto_playlist,
        "get_all_subscriptions",
        lambda svc: [
            {"channel_id": "UC1", "channel_title": "A"},
            {"channel_id": "UC2", "channel_title": "B"},
        ],
    )

    def fetch(service: object, channel_id: str, after: object) -> list:
        if channel_id == "UC2":
            raise KeyboardInterrupt
        return [video("v1")]

    monkeypatch.setattr(youtube_auto_playlist, "get_recent_videos_from_channel_rss", fetch)

    with pytest.raises(KeyboardInterrupt):
        youtube_auto_playlist.run()

    state = youtube_auto_playlist.load_state()
    assert state["processed_videos"] == ["v1"]
    assert state["last_check_time"] is None


def test_run_rejects_placeholder_playlist(run_env: MagicMock) -> None:
    """The placeholder playlist id aborts the run before any API use."""
    Path(youtube_auto_playlist.CONFIG_FILE).write_text(
        "youtube:\n  target_playlist_id: YOUR_PLAYLIST_ID_HERE\n", encoding="utf-8"
    )

    with pytest.raises(ValueError):
        youtube_auto_playlist.run()


# --- authenticate ---


def stub_login(monkeypatch: pytest.MonkeyPatch, fresh: MagicMock) -> None:
    """Make the interactive OAuth flow return fresh credentials and build() return a marker."""
    flow = MagicMock()
    flow.run_local_server.return_value = fresh
    monkeypatch.setattr(
        youtube_auto_playlist.InstalledAppFlow, "from_client_secrets_file", lambda *a, **k: flow
    )
    monkeypatch.setattr(youtube_auto_playlist, "build", lambda *a, **k: "service")


def test_authenticate_runs_fresh_flow_when_credentials_are_not_refreshable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid credentials without a refresh token trigger a new login, not a silent reuse."""
    stale = MagicMock(valid=False, expired=False, refresh_token=None)
    fresh = MagicMock()
    fresh.to_json.return_value = '{"token": "t"}'
    monkeypatch.setattr(youtube_auto_playlist, "load_credentials", lambda: stale)
    stub_login(monkeypatch, fresh)

    assert youtube_auto_playlist.authenticate() == "service"

    token = Path(youtube_auto_playlist.TOKEN_FILE).read_text(encoding="utf-8")
    assert token == '{"token": "t"}'


def test_authenticate_reuses_valid_credentials_without_rewriting_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid credentials are used as is and no token file is written."""
    monkeypatch.setattr(youtube_auto_playlist, "load_credentials", lambda: MagicMock(valid=True))
    monkeypatch.setattr(youtube_auto_playlist, "build", lambda *a, **k: "service")

    assert youtube_auto_playlist.authenticate() == "service"
    assert not Path(youtube_auto_playlist.TOKEN_FILE).exists()


def test_authenticate_deletes_revoked_token_and_logs_in_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid_grant refresh failure removes the token and starts a fresh login."""
    token_path = Path(youtube_auto_playlist.TOKEN_FILE)
    token_path.write_text("old", encoding="utf-8")
    expired = MagicMock(valid=False, expired=True, refresh_token="r")
    expired.refresh.side_effect = RefreshError("invalid_grant: Token has been revoked")
    fresh = MagicMock()
    fresh.to_json.return_value = "new"
    monkeypatch.setattr(youtube_auto_playlist, "AUTO_DELETE_INVALID_TOKEN", True)
    monkeypatch.setattr(youtube_auto_playlist, "load_credentials", lambda: expired)
    stub_login(monkeypatch, fresh)

    youtube_auto_playlist.authenticate()

    assert token_path.read_text(encoding="utf-8") == "new"


def test_authenticate_reraises_other_refresh_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refresh failures other than invalid_grant are not swallowed."""
    expired = MagicMock(valid=False, expired=True, refresh_token="r")
    expired.refresh.side_effect = RefreshError("server_error")
    monkeypatch.setattr(youtube_auto_playlist, "load_credentials", lambda: expired)

    with pytest.raises(RefreshError):
        youtube_auto_playlist.authenticate()


def test_load_credentials_returns_none_for_corrupt_token() -> None:
    """A truncated token file is treated as missing instead of crashing every cycle."""
    Path(youtube_auto_playlist.TOKEN_FILE).write_text("{trunc", encoding="utf-8")

    assert youtube_auto_playlist.load_credentials() is None


def test_load_credentials_returns_none_when_token_missing() -> None:
    """No token file means no credentials."""
    assert youtube_auto_playlist.load_credentials() is None
