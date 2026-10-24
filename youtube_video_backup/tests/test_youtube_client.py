"""Tests for youtube_client.py: parsing, quota state, RSS and API discovery, auth."""

import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

import youtube_client
from youtube_client import YouTubeClient, parse_feed_entries, parse_playlist_items
from utils import StorageManager

FEED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>vid1</yt:videoId>
    <title>First</title>
    <published>2024-01-01T10:00:00+00:00</published>
  </entry>
  <entry>
    <yt:videoId>vid2</yt:videoId>
    <title>Second</title>
    <published>2024-02-01T10:00:00+00:00</published>
  </entry>
</feed>"""

EMPTY_FEED_XML = (
    b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
)


@pytest.fixture
def storage():
    return StorageManager(SimpleNamespace())


@pytest.fixture
def client(storage):
    return YouTubeClient(SimpleNamespace(), storage)


def fake_urlopen(payload):
    """Return a urlopen replacement serving payload as a context manager."""
    def opener(url, timeout=None):
        return io.BytesIO(payload)
    return opener


def test_parse_feed_entries_skips_entries_without_video_id():
    entries = [
        SimpleNamespace(yt_videoid="a", title="A", published="2024"),
        SimpleNamespace(title="no id", published="2024"),
    ]
    assert parse_feed_entries(entries) == [{
        "id": "a", "title": "A", "published": "2024",
        "url": "https://www.youtube.com/watch?v=a",
    }]


def test_parse_playlist_items_drops_private_and_deleted():
    def item(video_id, title):
        return {"snippet": {
            "resourceId": {"videoId": video_id}, "title": title, "publishedAt": "2024",
        }}
    videos = parse_playlist_items([
        item("a", "Real"), item("b", "Private video"), item("c", "Deleted video"),
    ])
    assert [v["id"] for v in videos] == ["a"]


def test_new_day_resets_quota_and_persists(storage):
    storage.save_state({"quota_used_today": 900, "quota_reset_date": "2000-01-01"})
    client = YouTubeClient(SimpleNamespace(), storage)
    assert client.get_quota_today() == 0
    assert storage.load_state()["quota_used_today"] == 0


def test_same_day_keeps_quota(storage):
    today = youtube_client.datetime.now(youtube_client.PACIFIC_TZ).date().isoformat()
    storage.save_state({"quota_used_today": 900, "quota_reset_date": today})
    assert YouTubeClient(SimpleNamespace(), storage).get_quota_today() == 900


def test_state_without_reset_date_keeps_quota(storage):
    storage.save_state({"quota_used_today": 500})
    assert YouTubeClient(SimpleNamespace(), storage).get_quota_today() == 500


def test_quota_accumulates_and_saves(client, storage):
    client.add_quota_cost(1600)
    client.add_quota_cost(50)
    client.save_quota_state()
    assert client.get_quota_usage() == 1650
    assert storage.load_state()["quota_used_today"] == 1650


def test_rss_parses_entries(client, monkeypatch):
    monkeypatch.setattr(youtube_client.urllib.request, "urlopen", fake_urlopen(FEED_XML))
    videos = client.get_channel_videos_rss("UC1")
    assert [v["id"] for v in videos] == ["vid1", "vid2"]
    assert videos[0]["published"] == "2024-01-01T10:00:00+00:00"


def test_rss_empty_valid_feed_is_empty_list(client, monkeypatch):
    monkeypatch.setattr(youtube_client.urllib.request, "urlopen", fake_urlopen(EMPTY_FEED_XML))
    assert client.get_channel_videos_rss("UC1") == []


def test_rss_network_failure_raises_instead_of_empty(client, monkeypatch):
    def failing(url, timeout=None):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(youtube_client.urllib.request, "urlopen", failing)
    with pytest.raises(RuntimeError, match="Could not fetch RSS feed"):
        client.get_channel_videos_rss("UC1")


def test_rss_unparseable_payload_raises(client, monkeypatch):
    monkeypatch.setattr(youtube_client.urllib.request, "urlopen", fake_urlopen(b"<html><body>nope"))
    with pytest.raises(RuntimeError, match="Could not parse RSS feed"):
        client.get_channel_videos_rss("UC1")


class FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeApiService:
    def __init__(self, channel_response, pages):
        self.channel_response = channel_response
        self.pages = list(pages)
        self.page_tokens = []

    def channels(self):
        return SimpleNamespace(list=lambda **kw: FakeRequest(self.channel_response))

    def playlistItems(self):
        def list_page(**kw):
            self.page_tokens.append(kw.get("pageToken"))
            return FakeRequest(self.pages.pop(0))
        return SimpleNamespace(list=list_page)


def playlist_item(video_id, title="T"):
    return {"snippet": {"resourceId": {"videoId": video_id}, "title": title, "publishedAt": "2024"}}


CHANNEL_OK = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]}


def test_api_listing_follows_pages_and_counts_quota(client, paths, monkeypatch):
    with open(paths.api_key_file, "w", encoding="utf-8") as f:
        f.write("dummy-key\n")
    service = FakeApiService(CHANNEL_OK, [
        {"items": [playlist_item("a"), playlist_item("b", "Private video")], "nextPageToken": "p2"},
        {"items": [playlist_item("c")]},
    ])
    monkeypatch.setattr(youtube_client, "build", lambda *a, **kw: service)
    videos = client.get_all_channel_videos_api("UC1")
    assert [v["id"] for v in videos] == ["a", "c"]
    assert service.page_tokens == [None, "p2"]
    assert client.get_quota_usage() == 3  # one channel lookup plus two pages


def test_api_listing_requires_api_key(client):
    with pytest.raises(RuntimeError, match="API key not found"):
        client.get_all_channel_videos_api("UC1")


def test_api_listing_unknown_channel_raises(client, paths, monkeypatch):
    with open(paths.api_key_file, "w", encoding="utf-8") as f:
        f.write("dummy-key")
    service = FakeApiService({"items": []}, [])
    monkeypatch.setattr(youtube_client, "build", lambda *a, **kw: service)
    with pytest.raises(RuntimeError, match="not found"):
        client.get_all_channel_videos_api("UC1")


class FakeCredentials:
    valid = True

    def to_json(self):
        return json.dumps({"token": "fake"})


def test_authenticate_recovers_from_corrupt_token(client, paths, monkeypatch):
    with open(paths.token_file, "w", encoding="utf-8") as f:
        f.write("not json")

    def broken_loader(path, scopes):
        raise ValueError("bad token")

    class FakeFlow:
        def run_local_server(self, port=0):
            return FakeCredentials()

    monkeypatch.setattr(youtube_client.Credentials, "from_authorized_user_file", broken_loader)
    monkeypatch.setattr(
        youtube_client.InstalledAppFlow, "from_client_secrets_file",
        lambda path, scopes: FakeFlow(),
    )
    monkeypatch.setattr(youtube_client, "build", lambda *a, **kw: "service")
    assert client.authenticate() == "service"
    with open(paths.token_file, encoding="utf-8") as f:
        assert json.load(f) == {"token": "fake"}


def test_authenticated_channel_id_returns_id_and_counts_quota(client, storage):
    seen = {}

    def list_channels(**kw):
        seen.update(kw)
        return FakeRequest({"items": [{"id": "UC2"}]})

    client.service = SimpleNamespace(channels=lambda: SimpleNamespace(list=list_channels))
    assert client.get_authenticated_channel_id() == "UC2"
    assert seen == {"part": "id", "mine": True}
    assert client.get_quota_usage() == youtube_client.QUOTA_CHANNEL_LIST == 1
    assert storage.load_state()["quota_used_today"] == 1


@pytest.mark.parametrize("response", [{}, {"items": []}])
def test_authenticated_channel_id_none_when_no_channel(client, response):
    client.service = SimpleNamespace(
        channels=lambda: SimpleNamespace(list=lambda **kw: FakeRequest(response))
    )
    assert client.get_authenticated_channel_id() is None
    assert client.get_quota_usage() == 1
