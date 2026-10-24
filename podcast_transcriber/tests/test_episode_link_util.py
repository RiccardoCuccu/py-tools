"""Tests for episode_link_util: iTunes lookup, title matching and enclosure selection."""

import pytest

import episode_link_util as el

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Show</title>
  <item><title>Completely unrelated</title>
    <enclosure url="https://cdn.example/unrelated.mp3" type="audio/mpeg" length="1"/></item>
  <item><title>My Great Episode</title>
    <enclosure url="https://cdn.example/cover.jpg" type="image/jpeg" length="1"/>
    <enclosure url="https://cdn.example/great.mp3" type="audio/mpeg" length="1"/></item>
</channel></rss>
""".encode("utf-8")


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int = 200, payload: dict | None = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content

    def json(self) -> dict:
        return self._payload


def route_requests(monkeypatch: pytest.MonkeyPatch, lookup: FakeResponse, feed: FakeResponse) -> list:
    """Serve the iTunes lookup and the feed from fakes, recording each call."""
    calls: list = []

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        calls.append((url, kwargs))
        return lookup if url == el.ITUNES_LOOKUP_URL else feed

    monkeypatch.setattr(el.requests, "get", fake_get)
    return calls


# --- fetch_feed_url ---


def test_fetch_feed_url_returns_feed_and_passes_id_as_param(monkeypatch: pytest.MonkeyPatch) -> None:
    """The id travels as a query parameter (not string-built) and the feed URL is returned."""
    lookup = FakeResponse(payload={"resultCount": 1, "results": [{"feedUrl": "https://feed.example/rss"}]})
    calls = route_requests(monkeypatch, lookup, FakeResponse())

    assert el.fetch_feed_url("123&evil=1") == "https://feed.example/rss"
    assert calls[0][1]["params"] == {"id": "123&evil=1"}
    assert calls[0][1]["timeout"] == el.REQUEST_TIMEOUT_SECONDS


def test_fetch_feed_url_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-200 lookup response raises with the status code."""
    route_requests(monkeypatch, FakeResponse(status_code=500), FakeResponse())

    with pytest.raises(RuntimeError, match="500"):
        el.fetch_feed_url("1")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"resultCount": 0, "results": []}, "Podcast not found"),
        ({}, "Podcast not found"),
        ({"results": [{"collectionName": "no feed"}]}, "RSS feed URL not found"),
    ],
)
def test_fetch_feed_url_missing_data(
    monkeypatch: pytest.MonkeyPatch, payload: dict, message: str
) -> None:
    """Empty results and results without a feedUrl give clear errors."""
    route_requests(monkeypatch, FakeResponse(payload=payload), FakeResponse())

    with pytest.raises(LookupError, match=message):
        el.fetch_feed_url("1")


# --- find_best_entry ---


def test_find_best_entry_picks_closest_title() -> None:
    """The entry most similar to either wanted title is chosen."""
    entries = [{"title": "Other topic"}, {"title": "My Great Episode"}]

    entry, ratio = el.find_best_entry(entries, "my great episode", "")

    assert entry is entries[1]
    assert ratio == pytest.approx(1.0)


def test_find_best_entry_skips_entries_without_title() -> None:
    """Entries lacking a title are ignored instead of raising AttributeError."""
    entries = [{}, {"title": None}, {"title": "Match"}]

    entry, _ = el.find_best_entry(entries, "match")

    assert entry is entries[2]


def test_find_best_entry_empty_feed() -> None:
    """No entries means no match."""
    assert el.find_best_entry([], "x") == (None, 0.0)


# --- entry_audio_url ---


def test_entry_audio_url_prefers_audio_enclosure() -> None:
    """An audio/* enclosure beats an earlier non-audio one."""
    entry = {
        "enclosures": [
            {"href": "https://x/cover.jpg", "type": "image/jpeg"},
            {"href": "https://x/a.mp3", "type": "audio/mpeg"},
        ]
    }
    assert el.entry_audio_url(entry) == "https://x/a.mp3"


def test_entry_audio_url_uses_first_enclosure_without_types() -> None:
    """With no type information the first enclosure is used."""
    assert el.entry_audio_url({"enclosures": [{"href": "https://x/a"}]}) == "https://x/a"


def test_entry_audio_url_falls_back_to_link() -> None:
    """Without enclosures the entry link is the last resort."""
    assert el.entry_audio_url({"link": "https://x/page"}) == "https://x/page"


def test_entry_audio_url_none_when_nothing_available() -> None:
    """No enclosure and no link yields None."""
    assert el.entry_audio_url({"enclosures": [{"type": "audio/mpeg"}]}) is None


# --- episode_link ---


def lookup_ok() -> FakeResponse:
    """Build a successful iTunes lookup response."""
    return FakeResponse(payload={"results": [{"feedUrl": "https://feed.example/rss"}]})


def test_episode_link_returns_matching_audio_enclosure(monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end with fakes: the best title match's audio enclosure is returned."""
    calls = route_requests(monkeypatch, lookup_ok(), FakeResponse(content=RSS))

    url = el.episode_link("1", "my great episode", "My Great Episode")

    assert url == "https://cdn.example/great.mp3"
    assert calls[1][0] == "https://feed.example/rss"
    assert calls[1][1]["timeout"] == el.REQUEST_TIMEOUT_SECONDS


def test_episode_link_no_good_match_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Titles below the similarity threshold are rejected."""
    route_requests(monkeypatch, lookup_ok(), FakeResponse(content=RSS))

    with pytest.raises(LookupError, match="Episode not found"):
        el.episode_link("1", "zzzzzzzzzzzz", "qqqqqqqqqqqq")


def test_episode_link_feed_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing feed download raises instead of reporting an empty feed."""
    route_requests(monkeypatch, lookup_ok(), FakeResponse(status_code=404))

    with pytest.raises(RuntimeError, match="404"):
        el.episode_link("1", "a", "b")


def test_episode_link_match_without_audio_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A matched entry with neither enclosure nor link raises instead of returning None."""
    feed = b"<rss><channel><item><title>My Great Episode</title></item></channel></rss>"
    route_requests(monkeypatch, lookup_ok(), FakeResponse(content=feed))

    with pytest.raises(LookupError, match="no audio link"):
        el.episode_link("1", "my great episode", "My Great Episode")
