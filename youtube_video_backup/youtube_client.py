#!/usr/bin/env python3
"""
YouTube Client Module
Handles all YouTube API interactions, OAuth authentication, and RSS feed parsing
"""

import os
import sys
import json
from typing import List, Dict, Set, Optional, Any
from datetime import datetime, timezone
import feedparser
from googleapiclient.discovery import build, Resource
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from config import SCOPES, CLIENT_SECRET_FILE, TOKEN_FILE, API_KEY_FILE, STATE_FILE

class YouTubeClient:
    """Manages YouTube API interactions and authentication"""
    
    def __init__(self, config):
        self.config = config
        self.service: Optional[Resource] = None
        self.public_service: Optional[Resource] = None
        
        # Load quota state
        self.state = self._load_state()
        self._reset_quota_if_new_day()
        self.quota_used_today = self.state.get("quota_used_today", 0)
        self.quota_used_this_run = 0
    
    def _load_state(self):
        """Load state from file"""
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                # Ensure quota fields exist
                if "quota_used_today" not in state:
                    state["quota_used_today"] = 0
                if "quota_reset_date" not in state:
                    state["quota_reset_date"] = datetime.now(timezone.utc).date().isoformat()
                return state
        return {
            "quota_used_today": 0,
            "quota_reset_date": datetime.now(timezone.utc).date().isoformat(),
            "full_backup_completed": False,
            "last_backup_date": None,
            "total_videos_backed_up": 0
        }
    
    def _save_state(self):
        """Save state to file - preserves all state fields"""
        # Update quota fields without overwriting other state data
        self.state["quota_used_today"] = self.quota_used_today
        self.state["quota_reset_date"] = datetime.now(timezone.utc).date().isoformat()
        
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)
    
    def _reset_quota_if_new_day(self):
        """Reset quota counter if it's a new day (YouTube quota resets at midnight Pacific Time)"""
        today = datetime.now(timezone.utc).date().isoformat()
        last_reset = self.state.get("quota_reset_date", today)
        
        if today != last_reset:
            print(f"📅 New day detected - resetting quota counter (was {self.state.get('quota_used_today', 0)} units)")
            self.state["quota_used_today"] = 0
            self.state["quota_reset_date"] = today
            self._save_state()
    
    def add_quota_cost(self, cost):
        """Track API quota usage"""
        self.quota_used_today += cost
        self.quota_used_this_run += cost
        self._save_state()
    
    def get_quota_usage(self):
        """Get current quota usage for this run"""
        return self.quota_used_this_run
    
    def get_quota_today(self):
        """Get total quota used today"""
        return self.quota_used_today
    
    def show_quota_status(self):
        """Display current quota status"""
        daily_limit = 10000
        remaining = daily_limit - self.quota_used_today
        
        print(f"\n{'='*60}")
        print(f"📊 API QUOTA STATUS")
        print(f"{'='*60}")
        print(f"  • Used today: {self.quota_used_today:,} units")
        print(f"  • Remaining: {remaining:,} / {daily_limit:,} units")
        print(f"  • Reset: Midnight Pacific Time (PT/PDT)")
        
        if self.quota_used_today > 8000:
            print(f"\n  ⚠️  WARNING: High quota usage!")
            print(f"  You're close to the daily limit of 10,000 units")
        
        print(f"{'='*60}\n")
    
    def authenticate(self):
        """Authenticate user via OAuth2 and return YouTube service"""
        credentials = None
        
        if os.path.exists(TOKEN_FILE):
            credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
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
    
    def get_public_service(self):
        """Get YouTube service with API key for public data access"""
        api_key = self._load_api_key()
        if not api_key:
            print("ERROR: API key not found!")
            sys.exit(1)
        self.public_service = build("youtube", "v3", developerKey=api_key)
        return self.public_service
    
    def _load_api_key(self):
        """Load API key from file"""
        if os.path.exists(API_KEY_FILE):
            with open(API_KEY_FILE, 'r', encoding='utf-8') as f:
                return f.read().strip()
        return None
    
    def get_channel_videos_rss(self, channel_id):
        """Retrieve channel videos via RSS feed (no quota cost) - Returns ~15 most recent"""
        rss_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
        
        print(f"\n📡 Fetching recent videos from channel RSS feed...")
        feed = feedparser.parse(rss_url)
        
        videos = []
        for entry in feed.entries:
            video_id = entry.yt_videoid
            videos.append({
                'id': video_id,
                'title': entry.title,
                'published': entry.published,
                'url': f'https://www.youtube.com/watch?v={video_id}'
            })
        
        print(f"✓ Found {len(videos)} recent videos in RSS feed")
        return videos
    
    def get_all_channel_videos_api(self, channel_id):
        """Retrieve ALL videos from channel via API using public API key"""
        print(f"\n📡 Fetching ALL videos from channel via API...")
        print(f"   Using API key for public data access")
        print(f"   This will use API quota (~1 unit per 50 videos)")
        
        # Get public YouTube service
        if not self.public_service:
            self.get_public_service()
        
        assert self.public_service is not None  # Type hint for Pylance
        
        # Get the channel's "uploads" playlist
        channel_response = self.public_service.channels().list(  # type: ignore
            part='contentDetails',
            id=channel_id,
            fields='items(contentDetails/relatedPlaylists/uploads)'
        ).execute()
        self.add_quota_cost(1)
        
        if not channel_response.get('items'):
            print("⚠️  Channel not found!")
            return []
        
        uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        
        # Retrieve all videos from the uploads playlist
        videos = []
        next_page_token = None
        page_count = 0
        
        while True:
            page_count += 1
            print(f"   Fetching page {page_count}...", end='', flush=True)
            
            playlist_response = self.public_service.playlistItems().list(  # type: ignore
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=next_page_token,
                fields='nextPageToken,items(snippet(resourceId/videoId,title,publishedAt))'
            ).execute()
            self.add_quota_cost(1)
            
            for item in playlist_response.get('items', []):
                video_id = item['snippet']['resourceId']['videoId']
                videos.append({
                    'id': video_id,
                    'title': item['snippet']['title'],
                    'published': item['snippet']['publishedAt'],
                    'url': f'https://www.youtube.com/watch?v={video_id}'
                })
            
            print(f"\r   ✓ Page {page_count} fetched ({len(videos)} videos total)")
            
            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token:
                break
        
        print(f"✓ Found {len(videos)} total videos in channel")
        return videos
    
    def get_backup_channel_videos(self, channel_id):
        """Retrieve all video titles from the backup channel"""
        print(f"\n📋 Checking videos already present in backup channel...")
        
        # Ensure we have authenticated service
        if not self.service:
            self.authenticate()
        
        assert self.service is not None  # Type hint for Pylance
        
        # Get the channel's "uploads" playlist
        channel_response = self.service.channels().list(  # type: ignore
            part='contentDetails',
            id=channel_id,
            fields='items(contentDetails/relatedPlaylists/uploads)'
        ).execute()
        self.add_quota_cost(1)
        
        if not channel_response.get('items'):
            print("⚠️  Backup channel not found!")
            return set()
        
        uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        
        # Retrieve all video titles from the playlist
        backed_up_titles = set()
        next_page_token = None
        
        while True:
            playlist_response = self.service.playlistItems().list(  # type: ignore
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=next_page_token,
                fields='nextPageToken,items(snippet/title)'
            ).execute()
            self.add_quota_cost(1)
            
            for item in playlist_response.get('items', []):
                title = item['snippet']['title']
                backed_up_titles.add(title)
            
            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token:
                break
        
        print(f"✓ Found {len(backed_up_titles)} videos in backup channel")
        return backed_up_titles