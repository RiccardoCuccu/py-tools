"""Tests for youtube_client with googleapiclient and google-auth mocked."""

from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError

import youtube_client
from conftest import http_error, make_video
from utils import Logger
from youtube_client import YouTubeClient


@pytest.fixture
def client(fake_youtube):
    """A client wired to the in-memory service."""
    instance = YouTubeClient(Logger())
    instance.service = fake_youtube
    return instance


@pytest.mark.parametrize("value, expected", [
    ("PLabc_123-x", "PLabc_123-x"),
    ("WL", "WL"),
    (" PLabc ", "PLabc"),
    ("https://www.youtube.com/playlist?list=PLxyz", "PLxyz"),
    ("https://www.youtube.com/watch?v=abc&list=PLq1", "PLq1"),
])
def test_extract_playlist_id_accepts_ids_and_urls(value, expected):
    assert youtube_client.extract_playlist_id(value) == expected


@pytest.mark.parametrize("value", [
    "", "bad id!", "https://www.youtube.com/watch?v=abc", "a/b",
])
def test_extract_playlist_id_rejects_invalid(value):
    with pytest.raises(ValueError):
        youtube_client.extract_playlist_id(value)


def test_is_unlisted_checks_privacy_status():
    assert youtube_client.is_unlisted(make_video("a", "unlisted"))
    assert not youtube_client.is_unlisted(make_video("a", "public"))
    assert not youtube_client.is_unlisted({"id": "a"})


def test_to_unlisted_video_copies_playlists():
    playlists = ["P1"]
    video = youtube_client.to_unlisted_video(make_video("a", title="T"), playlists)
    assert video.url == "https://www.youtube.com/watch?v=a"
    assert (video.title, video.channel) == ("T", "Some Channel")
    playlists.append("P2")
    assert video.playlists == ["P1"]


def test_list_own_playlists_follows_pagination_and_counts_quota(client, fake_youtube):
    fake_youtube.playlists_data = [(f"PL{i}", f"List {i}") for i in range(5)]
    result = client.list_own_playlists()
    assert [p[0] for p in result] == [f"PL{i}" for i in range(5)]
    assert client.quota_used == 3


def test_get_playlist_title_found_and_fallback(client, fake_youtube):
    fake_youtube.playlists_data = [("PL1", "Mine")]
    assert client.get_playlist_title("PL1") == "Mine"
    assert client.get_playlist_title("PLunknown") == "PLunknown"


def test_list_playlist_video_ids_paginates(client, fake_youtube):
    fake_youtube.playlist_items["PL1"] = ["a", "b", "c"]
    assert client.list_playlist_video_ids("PL1") == ["a", "b", "c"]
    assert client.quota_used == 2


def test_list_playlist_video_ids_propagates_http_error(client, fake_youtube):
    fake_youtube.playlist_items["PL1"] = http_error(404)
    with pytest.raises(Exception, match="404"):
        client.list_playlist_video_ids("PL1")


def test_list_liked_videos_returns_resources(client, fake_youtube):
    fake_youtube.videos_data = {v: make_video(v) for v in "abc"}
    fake_youtube.liked = ["a", "b", "c"]
    assert [v["id"] for v in client.list_liked_videos()] == ["a", "b", "c"]


def test_fetch_videos_chunks_by_batch_size(client, fake_youtube, monkeypatch):
    monkeypatch.setattr(youtube_client, "VIDEOS_LIST_BATCH_SIZE", 2)
    ids = ["a", "b", "c", "d", "e"]
    fake_youtube.videos_data = {v: make_video(v) for v in ids}
    result = client.fetch_videos(ids)
    assert set(result) == set(ids)
    assert [len(b) for b in fake_youtube.videos_id_batches] == [2, 2, 1]
    assert client.quota_used == 3


def test_fetch_videos_omits_ids_the_api_does_not_return(client, fake_youtube):
    fake_youtube.videos_data = {"a": make_video("a")}
    assert set(client.fetch_videos(["a", "gone"])) == {"a"}


def test_fetch_videos_reuses_known_without_api_call(client, fake_youtube):
    known = {"a": make_video("a")}
    result = client.fetch_videos(["a"], known=known)
    assert result == known
    assert fake_youtube.videos_id_batches == []
    assert client.quota_used == 0


def _patch_auth(monkeypatch, credentials):
    """Mock the google-auth classes and googleapiclient.build."""
    creds_cls = MagicMock()
    creds_cls.from_authorized_user_file.return_value = credentials
    flow_cls = MagicMock()
    new_creds = MagicMock(valid=True)
    new_creds.to_json.return_value = '{"token": "new"}'
    flow_cls.from_client_secrets_file.return_value.run_local_server.return_value = (
        new_creds
    )
    build = MagicMock(return_value="service")
    monkeypatch.setattr(youtube_client, "Credentials", creds_cls)
    monkeypatch.setattr(youtube_client, "InstalledAppFlow", flow_cls)
    monkeypatch.setattr(youtube_client, "Request", MagicMock())
    monkeypatch.setattr(youtube_client, "build", build)
    return creds_cls, flow_cls, build


def test_authenticate_reuses_valid_token(paths, monkeypatch):
    paths.token_file.write_text("{}", encoding="utf-8")
    valid = MagicMock(valid=True)
    _, flow_cls, build = _patch_auth(monkeypatch, valid)
    client = YouTubeClient(Logger())
    assert client.authenticate() == "service"
    flow_cls.from_client_secrets_file.assert_not_called()
    build.assert_called_once_with("youtube", "v3", credentials=valid)


def test_authenticate_runs_consent_flow_and_saves_token(paths, monkeypatch):
    _, flow_cls, _ = _patch_auth(monkeypatch, None)
    YouTubeClient(Logger()).authenticate()
    flow_cls.from_client_secrets_file.assert_called_once()
    assert paths.token_file.read_text(encoding="utf-8") == '{"token": "new"}'


def test_authenticate_deletes_unrefreshable_token_and_relogs(paths, monkeypatch):
    paths.token_file.write_text("{}", encoding="utf-8")
    stale = MagicMock(valid=False, expired=True, refresh_token="r")
    stale.refresh.side_effect = RefreshError("revoked")
    _, flow_cls, _ = _patch_auth(monkeypatch, stale)
    YouTubeClient(Logger()).authenticate()
    flow_cls.from_client_secrets_file.assert_called_once()
    assert paths.token_file.read_text(encoding="utf-8") == '{"token": "new"}'


def test_authenticate_recovers_from_corrupt_token(paths, monkeypatch):
    paths.token_file.write_text("garbage", encoding="utf-8")
    creds_cls, flow_cls, _ = _patch_auth(monkeypatch, None)
    creds_cls.from_authorized_user_file.side_effect = ValueError("bad")
    YouTubeClient(Logger()).authenticate()
    flow_cls.from_client_secrets_file.assert_called_once()


def test_failed_call_still_counts_quota(client, fake_youtube):
    fake_youtube.playlist_items["PL1"] = http_error(500)
    with pytest.raises(Exception):
        client.list_playlist_video_ids("PL1")
    assert client.quota_used == 1


def test_authenticate_saves_token_without_leaving_temp_file(paths, monkeypatch):
    _patch_auth(monkeypatch, None)
    YouTubeClient(Logger()).authenticate()
    assert [p.name for p in paths.config_dir.iterdir()] == ["token.json"]
