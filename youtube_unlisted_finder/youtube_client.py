#!/usr/bin/env python3
"""
YouTube Data API access: OAuth, playlist listing, liked videos, classification.
"""

import os
import re
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import (
    API_PAGE_SIZE, CLIENT_SECRET_FILE, QUOTA_LIST_CALL_COST, SCOPES, TOKEN_FILE,
    VIDEOS_LIST_BATCH_SIZE,
)
from utils import Logger, UnlistedVideo, atomic_write_text

WATCH_URL_TEMPLATE = "https://www.youtube.com/watch?v={video_id}"
PRIVACY_UNLISTED = "unlisted"
PLAYLIST_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
VIDEO_FIELDS = "id,snippet(title,channelTitle),status/privacyStatus"


def extract_playlist_id(value: str) -> str:
    """
    Return the playlist id from a bare id or a URL with a list= parameter.

    Raises ValueError when the value is neither.
    """
    text = value.strip()
    if text.startswith(("http://", "https://")):
        ids = parse_qs(urlparse(text).query).get("list")
        if not ids:
            raise ValueError(f"no 'list' parameter in URL: {value}")
        text = ids[0]
    if not PLAYLIST_ID_PATTERN.fullmatch(text):
        raise ValueError(f"not a playlist id or URL: {value!r}")
    return text


def is_unlisted(resource: dict[str, Any]) -> bool:
    """Return True when a videos.list resource has privacyStatus unlisted."""
    return resource.get("status", {}).get("privacyStatus") == PRIVACY_UNLISTED


def to_unlisted_video(
    resource: dict[str, Any], playlists: list[str]
) -> UnlistedVideo:
    """Convert a videos.list resource into an UnlistedVideo."""
    snippet = resource.get("snippet", {})
    video_id = resource["id"]
    return UnlistedVideo(
        video_id=video_id,
        title=snippet.get("title", ""),
        channel=snippet.get("channelTitle", ""),
        url=WATCH_URL_TEMPLATE.format(video_id=video_id),
        playlists=list(playlists),
    )


class YouTubeClient:
    """Authenticated read-only YouTube Data API client with a quota counter."""

    def __init__(self, logger: Logger) -> None:
        """Create a client; call authenticate() before any API method."""
        self.logger = logger
        self.service: Any = None
        self.quota_used = 0

    def authenticate(self) -> Any:
        """
        Authenticate via OAuth2 and build the YouTube service.

        Reuses and refreshes the saved token; a token that cannot be refreshed
        is deleted and the browser consent flow runs again.
        """
        credentials = None
        if os.path.exists(TOKEN_FILE):
            try:
                credentials = Credentials.from_authorized_user_file(
                    TOKEN_FILE, SCOPES
                )
            except ValueError:
                self.logger.log_warning("OAuth token file is invalid, re-authenticating.")

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                try:
                    credentials.refresh(Request())
                except RefreshError:
                    self.logger.log_warning(
                        "OAuth token could not be refreshed, re-authenticating."
                    )
                    os.remove(TOKEN_FILE)
                    credentials = None
            if not credentials or not credentials.valid:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CLIENT_SECRET_FILE, SCOPES
                )
                credentials = flow.run_local_server(port=0)
            atomic_write_text(TOKEN_FILE, credentials.to_json())

        self.service = build("youtube", "v3", credentials=credentials)
        return self.service

    def _call(self, request: Any) -> dict[str, Any]:
        """Execute one list request; the quota is counted even if the call fails."""
        self.quota_used += QUOTA_LIST_CALL_COST
        return request.execute()

    def _pages(self, make_request: Callable[[str | None], Any]) -> Iterator[Any]:
        """Yield every response page of a paged list call."""
        token = None
        while True:
            response = self._call(make_request(token))
            yield response
            token = response.get("nextPageToken")
            if not token:
                return

    def list_own_playlists(self) -> list[tuple[str, str]]:
        """Return (playlist_id, title) for every playlist of the account."""
        playlists = []
        for page in self._pages(lambda token: self.service.playlists().list(
            part="snippet", mine=True, maxResults=API_PAGE_SIZE, pageToken=token,
            fields="nextPageToken,items(id,snippet/title)",
        )):
            for item in page.get("items", []):
                playlists.append((item["id"], item["snippet"]["title"]))
        return playlists

    def get_playlist_title(self, playlist_id: str) -> str:
        """Return a playlist title, or the id itself when it cannot be read."""
        response = self._call(self.service.playlists().list(
            part="snippet", id=playlist_id, fields="items(id,snippet/title)",
        ))
        items = response.get("items", [])
        return items[0]["snippet"]["title"] if items else playlist_id

    def list_playlist_video_ids(self, playlist_id: str) -> list[str]:
        """Return the video ids of every item in a playlist."""
        ids = []
        for page in self._pages(lambda token: self.service.playlistItems().list(
            part="contentDetails", playlistId=playlist_id,
            maxResults=API_PAGE_SIZE, pageToken=token,
            fields="nextPageToken,items(contentDetails/videoId)",
        )):
            for item in page.get("items", []):
                ids.append(item["contentDetails"]["videoId"])
        return ids

    def list_liked_videos(self) -> list[dict[str, Any]]:
        """Return the liked videos as videos.list resources (already classified)."""
        videos = []
        for page in self._pages(lambda token: self.service.videos().list(
            part="snippet,status", myRating="like", maxResults=API_PAGE_SIZE,
            pageToken=token, fields=f"nextPageToken,items({VIDEO_FIELDS})",
        )):
            videos.extend(page.get("items", []))
        return videos

    def fetch_videos(
        self, video_ids: list[str], known: dict[str, dict[str, Any]] | None = None
    ) -> dict[str, dict[str, Any]]:
        """
        Return videos.list resources for the given ids, keyed by id.

        Resources in known are reused without an API call. Ids the API does not
        return (private or deleted videos) are absent from the result.
        """
        known = known or {}
        resources = {vid: known[vid] for vid in video_ids if vid in known}
        missing = [vid for vid in video_ids if vid not in known]
        for start in range(0, len(missing), VIDEOS_LIST_BATCH_SIZE):
            chunk = missing[start:start + VIDEOS_LIST_BATCH_SIZE]
            response = self._call(self.service.videos().list(
                part="snippet,status", id=",".join(chunk),
                fields=f"items({VIDEO_FIELDS})",
            ))
            for item in response.get("items", []):
                resources[item["id"]] = item
        return resources
