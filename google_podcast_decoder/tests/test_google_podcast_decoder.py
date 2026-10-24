"""Tests for google_podcast_decoder: URL decoding, RSS parsing, fetching and the CLI."""

import base64

import pytest
import requests

import google_podcast_decoder as gpd

FEED_URL = "https://example.com/feed.xml"
GUID = "episode-guid-123"

RSS = """<?xml version="1.0"?>
<rss><channel>
  <title>My Show</title>
  <description>Show &lt;b&gt;desc&lt;/b&gt;</description>
  <item>
    <guid>other-guid</guid>
    <title>Other</title>
  </item>
  <item>
    <guid isPermaLink="false">episode-guid-123</guid>
    <title>Target</title>
    <description>Line one&lt;br/&gt;Line &amp;amp; two</description>
    <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
    <link>https://example.com/ep</link>
    <enclosure url="https://example.com/a.mp3" type="audio/mpeg"/>
  </item>
</channel></rss>
""".encode("utf-8")


def encode(text: str, urlsafe: bool = False, pad: bool = False) -> str:
    """Base64-encode text the way a Google Podcasts URL segment is built."""
    raw = text.encode("utf-8")
    out = (base64.urlsafe_b64encode(raw) if urlsafe else base64.b64encode(raw)).decode("ascii")
    return out if pad else out.rstrip("=")


def google_url(feed: str = FEED_URL, guid: str = GUID, suffix: str = "") -> str:
    """Build a Google Podcasts episode URL for the given feed and guid."""
    return f"https://podcasts.google.com/feed/{encode(feed)}/episode/{encode(guid)}{suffix}"


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int = 200, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


# --- strip_html ---


def test_strip_html_converts_br_removes_tags_and_unescapes() -> None:
    """Line breaks become newlines, tags vanish, entities are decoded."""
    assert gpd.strip_html("a<br>b<BR/>c <b>bold</b> &amp; &lt;x&gt;") == "a\nb\nc bold & <x>"


def test_strip_html_handles_none() -> None:
    """A missing description yields an empty string instead of crashing."""
    assert gpd.strip_html(None) == ""


# --- URL parsing and decoding ---


def test_extract_encoded_parts_stops_at_query_and_fragment() -> None:
    """Query strings and fragments are not part of the episode segment."""
    url = "https://podcasts.google.com/feed/AAA/episode/BBB?sa=X#frag"
    assert gpd.extract_encoded_parts_from_url(url) == ("AAA", "BBB")


def test_extract_encoded_parts_stops_at_trailing_slash() -> None:
    """A trailing slash is not part of the episode segment."""
    url = "https://podcasts.google.com/feed/AAA/episode/BBB/"
    assert gpd.extract_encoded_parts_from_url(url) == ("AAA", "BBB")


@pytest.mark.parametrize(
    "url",
    ["", "https://example.com/feed/AAA/episode/BBB", "https://podcasts.google.com/feed/AAA"],
)
def test_extract_encoded_parts_rejects_other_urls(url: str) -> None:
    """URLs that are not Google Podcasts episode links raise ValueError."""
    with pytest.raises(ValueError):
        gpd.extract_encoded_parts_from_url(url)


def test_decode_round_trip_with_stripped_padding() -> None:
    """Segments without Base64 padding decode correctly."""
    assert gpd.decode_google_podcasts_url(google_url()) == (FEED_URL, GUID)


def test_decode_accepts_urlsafe_alphabet() -> None:
    """URL-safe Base64 (- and _) decodes like the standard alphabet."""
    feed = "https://example.com/feed?a=b>c~d"
    url = f"https://podcasts.google.com/feed/{encode(feed, urlsafe=True)}/episode/{encode(GUID, urlsafe=True)}"
    assert gpd.decode_google_podcasts_url(url) == (feed, GUID)


def test_decode_accepts_padded_and_percent_encoded_segments() -> None:
    """Padding kept as %3D in the URL is understood."""
    feed_segment = encode(FEED_URL, pad=True).replace("=", "%3D")
    url = f"https://podcasts.google.com/feed/{feed_segment}/episode/{encode(GUID)}"
    assert gpd.decode_google_podcasts_url(url) == (FEED_URL, GUID)


def test_decode_rejects_invalid_base64() -> None:
    """Garbage in a segment becomes a ValueError, not a traceback."""
    with pytest.raises(ValueError):
        gpd.decode_google_podcasts_url("https://podcasts.google.com/feed/!!!!/episode/BBBB")


def test_decode_rejects_non_utf8_payload() -> None:
    """Valid Base64 of non-UTF-8 bytes is rejected."""
    bad = base64.b64encode(b"\xff\xfe\xfd").decode("ascii")
    with pytest.raises(ValueError):
        gpd.decode_base64_text(bad)


@pytest.mark.parametrize("feed", ["file:///etc/passwd", "ftp://example.com/x", "not a url"])
def test_decode_rejects_non_http_feed_urls(feed: str) -> None:
    """Only http(s) feed URLs are accepted, so local files cannot be requested."""
    with pytest.raises(ValueError):
        gpd.decode_google_podcasts_url(google_url(feed=feed))


# --- find_episode_in_feed ---


def test_find_episode_returns_metadata() -> None:
    """The matching item's fields and the show info are returned."""
    episode = gpd.find_episode_in_feed(RSS, GUID)

    assert episode is not None
    assert episode["title"] == "Target"
    assert episode["publication_date"].startswith("Mon, 01 Jan 2024")
    assert episode["link"] == "https://example.com/ep"
    assert episode["audio_url"] == "https://example.com/a.mp3"
    assert episode["show_info"]["show_title"] == "My Show"


def test_find_episode_missing_returns_none() -> None:
    """An unknown guid yields None."""
    assert gpd.find_episode_in_feed(RSS, "nope") is None


def test_find_episode_empty_id_does_not_match_everything() -> None:
    """An empty episode id must not match the first item through substring logic."""
    assert gpd.find_episode_in_feed(RSS, "") is None


def test_find_episode_prefers_exact_guid_over_substring() -> None:
    """When one guid contains another, the exact match wins regardless of order."""
    feed = b"""<rss><channel><item><guid>abc-extended</guid><title>Wrong</title></item>
    <item><guid>abc</guid><title>Right</title></item></channel></rss>"""

    episode = gpd.find_episode_in_feed(feed, "abc")

    assert episode is not None
    assert episode["title"] == "Right"


def test_find_episode_falls_back_to_substring_match() -> None:
    """A guid that embeds the id (e.g. a URL guid) still matches."""
    feed = b"<rss><channel><item><guid>https://x/ep/abc</guid><title>T</title></item></channel></rss>"
    episode = gpd.find_episode_in_feed(feed, "abc")
    assert episode is not None and episode["title"] == "T"


def test_find_episode_tolerates_missing_fields() -> None:
    """Items without optional children and feeds without a channel do not crash."""
    feed = b"<rss><item><guid>g1</guid><description></description></item></rss>"

    episode = gpd.find_episode_in_feed(feed, "g1")

    assert episode is not None
    assert episode["title"] == "N/A"
    assert episode["description"] == "N/A"
    assert episode["show_info"]["show_title"] == "N/A"
    assert "audio_url" not in episode


def test_find_episode_invalid_xml_returns_none() -> None:
    """Unparseable feed content returns None instead of raising."""
    assert gpd.find_episode_in_feed(b"<rss><item>", "x") is None


def test_find_episode_empty_content_returns_none() -> None:
    """Empty feed content returns None."""
    assert gpd.find_episode_in_feed(b"", "x") is None
    assert gpd.find_episode_in_feed(None, "x") is None


# --- fetch_rss_feed ---


def test_fetch_returns_content_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 response yields its body; the timeout and headers are passed."""
    seen: dict = {}

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        seen.update(kwargs, url=url)
        return FakeResponse(200, b"<rss/>")

    monkeypatch.setattr(gpd.requests, "get", fake_get)

    assert gpd.fetch_rss_feed(FEED_URL) == b"<rss/>"
    assert seen["timeout"] == gpd.FETCH_TIMEOUT_SECONDS
    assert "User-Agent" in seen["headers"]


def test_fetch_returns_none_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-200 status yields None."""
    monkeypatch.setattr(gpd.requests, "get", lambda *a, **k: FakeResponse(404))
    assert gpd.fetch_rss_feed(FEED_URL) is None


def test_fetch_returns_none_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection failure yields None."""

    def boom(*args: object, **kwargs: object) -> None:
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(gpd.requests, "get", boom)
    assert gpd.fetch_rss_feed(FEED_URL) is None


# --- main ---


def test_main_prints_episode_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end with a faked feed: details are printed and the exit code is 0."""
    monkeypatch.setattr(gpd.requests, "get", lambda *a, **k: FakeResponse(200, RSS))

    code = gpd.main([google_url()])

    out = capsys.readouterr().out
    assert code == 0
    assert "Title: Target" in out
    assert "Audio URL: https://example.com/a.mp3" in out
    assert "Line one\nLine & two" in out


def test_main_episode_not_found_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A feed without the episode reports it and exits non-zero."""
    monkeypatch.setattr(gpd.requests, "get", lambda *a, **k: FakeResponse(200, RSS))

    assert gpd.main([google_url(guid="missing")]) == 1
    assert "NOT found" in capsys.readouterr().out


def test_main_fetch_failure_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable feed exits non-zero."""
    monkeypatch.setattr(gpd.requests, "get", lambda *a, **k: FakeResponse(500))
    assert gpd.main([google_url()]) == 1


def test_main_invalid_url_exits_one(capsys: pytest.CaptureFixture[str]) -> None:
    """An invalid URL prints an error and exits non-zero without any request."""
    assert gpd.main(["https://example.com/nothing"]) == 1
    assert "Error:" in capsys.readouterr().out


def test_main_prompts_when_no_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a URL argument the user is prompted; an empty answer is rejected."""
    monkeypatch.setattr("builtins.input", lambda prompt="": "   ")
    assert gpd.main([]) == 1
