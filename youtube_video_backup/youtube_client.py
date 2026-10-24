#!/usr/bin/env python3
"""
YouTube Client Module
Handles all YouTube API interactions, OAuth authentication, and RSS feed parsing
"""

import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Optional

import feedparser
import pytz
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

from config import SCOPES, CLIENT_SECRET_FILE, TOKEN_FILE, API_KEY_FILE

# YouTube API Quota Costs (as per YouTube Data API v3 documentation)
QUOTA_DAILY_LIMIT = 10000
QUOTA_HIGH_USAGE_THRESHOLD = 8000
QUOTA_CHANNEL_LIST = 1
QUOTA_PLAYLIST_ITEMS_LIST = 1

# RSS feed access
RSS_URL_TEMPLATE = 'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
RSS_TIMEOUT_SECONDS = 30
WATCH_URL_TEMPLATE = 'https://www.youtube.com/watch?v={video_id}'

# Placeholder titles of uploads-playlist entries whose video cannot be downloaded
UNAVAILABLE_VIDEO_TITLES = {'Private video', 'Deleted video'}

# Pacific Time timezone (handles PST/PDT automatically)
PACIFIC_TZ = pytz.timezone('US/Pacific')


def parse_feed_entries(entries: list[Any]) -> list[dict[str, str]]:
    """Convert feedparser entries into video dicts, skipping entries without an id."""
    videos = []
    for entry in entries:
        video_id = getattr(entry, 'yt_videoid', None)
        if not video_id:
            continue
        videos.append({
            'id': video_id,
            'title': entry.title,
            'published': entry.published,
            'url': WATCH_URL_TEMPLATE.format(video_id=video_id),
        })
    return videos


def parse_playlist_items(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Convert playlistItems API entries into video dicts.

    Private and deleted uploads stay in the playlist as placeholders that yt-dlp
    can never download, so they are dropped instead of failing every run.
    """
    videos = []
    for item in items:
        snippet = item['snippet']
        if snippet['title'] in UNAVAILABLE_VIDEO_TITLES:
            continue
        video_id = snippet['resourceId']['videoId']
        videos.append({
            'id': video_id,
            'title': snippet['title'],
            'published': snippet['publishedAt'],
            'url': WATCH_URL_TEMPLATE.format(video_id=video_id),
        })
    return videos


class YouTubeClient:
    """Manages YouTube API interactions and authentication"""
    
    def __init__(self, config, storage_manager):
        """Initialise the YouTube client and restore today's quota usage from state."""
        self.config = config
        self.storage = storage_manager
        self.service: Optional[Resource] = None
        
        # Load quota state from storage
        state = self.storage.load_state()
        self._reset_quota_if_new_day(state)
        self.quota_used_today = state.get("quota_used_today", 0)
        self.quota_used_this_run = 0
    
    def _reset_quota_if_new_day(self, state):
        """Reset quota counter if it's a new day (YouTube quota resets at midnight Pacific Time)"""
        # Get current time in Pacific timezone
        now_pacific = datetime.now(PACIFIC_TZ)
        current_date_pacific = now_pacific.date().isoformat()
        
        # Get last reset date (stored as Pacific date)
        # A state without a date has no usage to reset yet
        last_reset = state.get("quota_reset_date", current_date_pacific)
        
        # Check if we've crossed midnight Pacific Time
        if current_date_pacific != last_reset:
            print(f"📅 New day detected in Pacific Time - resetting quota counter")
            print(f"   (was {state.get('quota_used_today', 0)} units)")
            state["quota_used_today"] = 0
            state["quota_reset_date"] = current_date_pacific
            self.quota_used_today = 0
            self.storage.save_state(state)
    
    def add_quota_cost(self, cost):
        """Track API quota usage (in memory only)"""
        self.quota_used_today += cost
        self.quota_used_this_run += cost
    
    def save_quota_state(self):
        """Explicitly save quota state to disk"""
        state = self.storage.load_state()
        state["quota_used_today"] = self.quota_used_today
        state["quota_reset_date"] = datetime.now(PACIFIC_TZ).date().isoformat()
        self.storage.save_state(state)
    
    def get_quota_usage(self):
        """Get current quota usage for this run"""
        return self.quota_used_this_run
    
    def get_quota_today(self):
        """Get total quota used today"""
        return self.quota_used_today
    
    def show_quota_status(self):
        """Display current quota status"""
        remaining = QUOTA_DAILY_LIMIT - self.quota_used_today
        
        print(f"\n{'='*60}")
        print(f"📊 API QUOTA STATUS")
        print(f"{'='*60}")
        print(f"  • Used today: {self.quota_used_today:,} units")
        print(f"  • Remaining: {remaining:,} / {QUOTA_DAILY_LIMIT:,} units")
        print(f"  • Reset: Midnight Pacific Time (PT/PDT)")
        
        if self.quota_used_today > QUOTA_HIGH_USAGE_THRESHOLD:
            print(f"\n  ⚠️  WARNING: High quota usage!")
            print(f"  You're close to the daily limit of {QUOTA_DAILY_LIMIT:,} units")
        
        print(f"{'='*60}\n")
    
    def authenticate(self):
        """Authenticate user via OAuth2 and return YouTube service"""
        credentials = None
        
        if os.path.exists(TOKEN_FILE):
            try:
                credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            except ValueError:
                # Corrupt or incomplete token file: fall through to a fresh login
                print("⚠️  OAuth token file is invalid. Re-authenticating...")
        
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                try:
                    credentials.refresh(Request())
                except RefreshError:
                    print("⚠️  OAuth token expired and could not be refreshed. Re-authenticating...")
                    os.remove(TOKEN_FILE)
                    credentials = None
            if not credentials or not credentials.valid:
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        CLIENT_SECRET_FILE,
                        SCOPES
                    )
                    credentials = flow.run_local_server(port=0)
                except KeyboardInterrupt:
                    print("\n\nAuthentication cancelled by user")
                    sys.exit(0)
            
            with open(TOKEN_FILE, "w", encoding="utf-8") as token_file:
                token_file.write(credentials.to_json())
        
        self.service = build("youtube", "v3", credentials=credentials)
        return self.service
    
    def get_authenticated_channel_id(self):
        """
        Return the id of the channel the OAuth credentials upload to.

        Costs QUOTA_CHANNEL_LIST units. Returns None when the response has no channel.
        """
        if self.service is None:
            raise RuntimeError("authenticate() must be called first")
        service: Any = self.service  # Resource builds its methods dynamically
        response = service.channels().list(part="id", mine=True).execute()
        self.add_quota_cost(QUOTA_CHANNEL_LIST)
        self.save_quota_state()
        items = response.get("items") or []
        return items[0].get("id") if items else None

    def _load_api_key(self):
        """Load API key from file"""
        if os.path.exists(API_KEY_FILE):
            with open(API_KEY_FILE, 'r', encoding='utf-8') as f:
                return f.read().strip()
        return None
    
    def get_channel_videos_rss(self, channel_id):
        """Retrieve channel videos via RSS feed (no quota cost) - Returns ~15 most recent

        Raises RuntimeError when the feed cannot be fetched or parsed, so a network
        failure is never mistaken for an empty channel.
        """
        rss_url = RSS_URL_TEMPLATE.format(channel_id=channel_id)

        print(f"\n📡 Fetching recent videos from channel RSS feed...")
        # feedparser has no network timeout of its own, so fetch the bytes here
        try:
            with urllib.request.urlopen(rss_url, timeout=RSS_TIMEOUT_SECONDS) as response:
                payload = response.read()
        except (urllib.error.URLError, OSError) as e:
            raise RuntimeError(f"Could not fetch RSS feed: {e}") from e

        feed = feedparser.parse(payload)
        if not feed.entries and feed.get('bozo'):
            raise RuntimeError(f"Could not parse RSS feed: {feed.get('bozo_exception')}")

        videos = parse_feed_entries(feed.entries)
        print(f"✓ Found {len(videos)} recent videos in RSS feed")
        return videos

    def get_all_channel_videos_api(self, channel_id):
        """Retrieve ALL videos from channel via API using public API key"""
        print(f"\n📡 Fetching ALL videos from channel via API...")
        print(f"   Using API key for public data access")
        print(f"   This will use API quota (~{QUOTA_PLAYLIST_ITEMS_LIST} unit per 50 videos)")
        
        # Load API key and create service
        api_key = self._load_api_key()
        if not api_key:
            raise RuntimeError(f"API key not found at {API_KEY_FILE}")
        
        # Create public service with API key
        public_service = build("youtube", "v3", developerKey=api_key)
        
        # Get the channel's "uploads" playlist
        channel_response = public_service.channels().list(
            part='contentDetails',
            id=channel_id,
            fields='items(contentDetails/relatedPlaylists/uploads)'
        ).execute()
        self.add_quota_cost(QUOTA_CHANNEL_LIST)
        
        if not channel_response.get('items'):
            raise RuntimeError(
                f"Channel '{channel_id}' not found or not accessible with the provided API key"
            )
        
        uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        
        # Retrieve all videos from the uploads playlist
        videos = []
        next_page_token = None
        page_count = 0
        
        while True:
            page_count += 1
            print(f"   Fetching page {page_count}...", end='', flush=True)
            
            playlist_response = public_service.playlistItems().list(
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=next_page_token,
                fields='nextPageToken,items(snippet(resourceId/videoId,title,publishedAt))'
            ).execute()
            self.add_quota_cost(QUOTA_PLAYLIST_ITEMS_LIST)
            
            videos.extend(parse_playlist_items(playlist_response.get('items', [])))
            
            print(f"\r   ✓ Page {page_count} fetched ({len(videos)} videos total)")
            
            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token:
                break
        
        print(f"✓ Found {len(videos)} total videos in channel")
        return videos