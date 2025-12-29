#!/usr/bin/env python3
"""
YouTube Video Backup Script
Downloads videos from a YouTube channel and re-uploads them to a secondary channel as private
"""

import os
import json
import sys
import time
import feedparser
import yt_dlp
from pathlib import Path
from datetime import datetime, timezone
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from typing import Dict, Set, List, Any, Optional

# =====================================
# GENERAL CONFIGURATION - EDIT THESE VALUES
# =====================================

# Script Behavior
DRY_RUN = False                                         # Set to True to simulate without actually uploading videos
AUTO_CONFIRM = False                                    # Set to True to skip confirmation prompts for each video
USE_API_FALLBACK = True                                 # Set to True to use YouTube API if yt-dlp fails
DOWNLOAD_DELAY_SECONDS = 2                              # Delay between downloads to avoid rate limiting
INITIAL_FULL_BACKUP = True                              # Set to True to do full channel backup via API (first run only)
                                                        # After first complete backup, set to False or delete state file to trigger again

# File Paths
CONFIG_FILE = "config.json"                             # User-specific settings (not in repository)
CLIENT_SECRET_FILE = "client_secret.json"               # OAuth credentials file (not in repository)
TOKEN_FILE = "token.json"                               # OAuth token cache (auto-generated)
STATE_FILE = "state.json"                               # Backup state tracker (auto-generated)
ARCHIVE_FILE = "archive.txt"                            # Archive of processed videos (auto-generated)
COOKIE_FILE = "cookies.txt"                             # YouTube cookies for yt-dlp (required)
LOG_FILE = "log.txt"                                    # Log of backed up videos (auto-generated)
API_KEY_FILE = "api_key.txt"                            # YouTube API key for public data access (not in repository)

# =====================================
# TECHNICAL CONFIGURATION (DO NOT EDIT)
# =====================================

SCOPES = ['https://www.googleapis.com/auth/youtube.upload',
          'https://www.googleapis.com/auth/youtube.readonly']

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Make all file paths relative to script directory
CONFIG_FILE = os.path.join(SCRIPT_DIR, CONFIG_FILE)
CLIENT_SECRET_FILE = os.path.join(SCRIPT_DIR, CLIENT_SECRET_FILE)
TOKEN_FILE = os.path.join(SCRIPT_DIR, TOKEN_FILE)
ARCHIVE_FILE = os.path.join(SCRIPT_DIR, ARCHIVE_FILE)
COOKIE_FILE = os.path.join(SCRIPT_DIR, COOKIE_FILE)
LOG_FILE = os.path.join(SCRIPT_DIR, LOG_FILE)
STATE_FILE = os.path.join(SCRIPT_DIR, STATE_FILE)
API_KEY_FILE = os.path.join(SCRIPT_DIR, API_KEY_FILE)
DOWNLOAD_DIR = os.path.join(SCRIPT_DIR, 'downloads')

# Global quota tracking
quota_used = 0

# =====================================
# LOGGING UTILITIES
# =====================================

def log_backed_up_video(video_id, video_title, channel_title, backup_video_id):
    """Log backed up video to file and print compact one-line format"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_url = f"https://www.youtube.com/watch?v={video_id}"
    backup_url = f"https://www.youtube.com/watch?v={backup_video_id}"
    log_entry = f"[{timestamp}] {channel_title} - {video_title}\n  Source: {source_url}\n  Backup: {backup_url}\n\n"
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)
    
    print(f"  ✓ {video_title}")
    print(f"    Source: {source_url}")
    print(f"    Backup: {backup_url}")

# =====================================
# FIRST RUN SETUP
# =====================================

def create_default_config():
    """Create a default backup_config.json file with placeholders"""
    default_config = {
        "source_channel_id": "YOUR_SOURCE_CHANNEL_ID_HERE",
        "backup_channel_id": "YOUR_BACKUP_CHANNEL_ID_HERE"
    }
    
    with open(CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump(default_config, file, indent=2)
    
    print(f"✓ Created {CONFIG_FILE}")
    return default_config

def check_client_secret():
    """Check if client_secret.json exists"""
    return os.path.exists(CLIENT_SECRET_FILE)

def check_api_key():
    """Check if api_key.txt exists"""
    return os.path.exists(API_KEY_FILE)

def load_api_key():
    """Load API key from file"""
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return None

def check_cookies():
    """Check if cookies.txt exists"""
    # Cookies are optional - we have API fallback
    return True

def prompt_for_channel_ids():
    """Prompt user for Source and Backup Channel IDs"""
    print(f"\n{'='*60}")
    print("CHANNEL IDs REQUIRED")
    print(f"{'='*60}\n")
    print("You need to provide two channel IDs:\n")
    print("1. SOURCE CHANNEL (to download from)")
    print("2. BACKUP CHANNEL (private backup destination)\n")
    print("How to find your Channel ID:")
    print("  1. Go to YouTube Studio: https://studio.youtube.com")
    print("  2. Click on 'Settings' (gear icon)")
    print("  3. Click on 'Channel' → 'Advanced settings'")
    print("  4. Your Channel ID is shown there")
    print("  5. Or go to: https://www.youtube.com/account_advanced\n")
    
    while True:
        source_id = input("Enter SOURCE Channel ID: ").strip()
        if source_id and source_id != "YOUR_SOURCE_CHANNEL_ID_HERE":
            break
        print("❌ Invalid Channel ID. Please try again.\n")
    
    while True:
        backup_id = input("Enter BACKUP Channel ID: ").strip()
        if backup_id and backup_id != "YOUR_BACKUP_CHANNEL_ID_HERE":
            break
        print("❌ Invalid Channel ID. Please try again.\n")
    
    return source_id, backup_id

def first_run_setup():
    """Guide user through first-run configuration"""
    print("\n" + "="*60)
    print("FIRST RUN SETUP - YouTube Video Backup Script")
    print("="*60 + "\n")
    
    # Check for client_secret.json first
    if not check_client_secret():
        print(f"⚠  Missing {CLIENT_SECRET_FILE}!\n")
        print(f"┌────────────────────────────────────────────────────────┐")
        print(f"│ STEP-BY-STEP: Get OAuth 2.0 Credentials                │")
        print(f"└────────────────────────────────────────────────────────┘\n")
        
        print(f"📋 STEP 1: Create/Select Google Cloud Project")
        print(f"   → Go to: https://console.cloud.google.com/")
        print(f"   → Click 'Select a project' → 'NEW PROJECT'")
        print(f"   → Enter a project name → Click 'CREATE'\n")
        
        print(f"📋 STEP 2: Enable YouTube Data API v3")
        print(f"   → Go to: https://console.cloud.google.com/apis/library")
        print(f"   → Search for 'YouTube Data API v3'")
        print(f"   → Click on it → Click 'ENABLE'\n")
        
        print(f"📋 STEP 3: Configure OAuth Consent Screen")
        print(f"   → Go to: https://console.cloud.google.com/apis/credentials/consent")
        print(f"   → Select 'External' → Click 'CREATE'")
        print(f"   → Fill in App name and User support email")
        print(f"   → Click 'SAVE AND CONTINUE' through screens")
        print(f"   → ⚠️ On 'Test users' screen:")
        print(f"     - Click 'ADD USERS'")
        print(f"     - Enter your email address")
        print(f"     - Click 'ADD' then 'SAVE AND CONTINUE'\n")
        
        print(f"📋 STEP 4: Create OAuth 2.0 Client ID")
        print(f"   → Go to: https://console.cloud.google.com/apis/credentials")
        print(f"   → Click 'CREATE CREDENTIALS' → 'OAuth client ID'")
        print(f"   → Application type: Select 'Desktop app'")
        print(f"   → Name: (e.g., 'YouTube Video Backup')")
        print(f"   → Click 'CREATE'\n")
        
        print(f"📋 STEP 5: Download Credentials")
        print(f"   → In the popup, click 'DOWNLOAD JSON'")
        print(f"   → Or: Go to Credentials page → Click download icon (⬇)")
        print(f"   → Rename the file to: {os.path.basename(CLIENT_SECRET_FILE)}")
        print(f"   → Move it to: {os.path.dirname(CLIENT_SECRET_FILE)}\n")
        
        print(f"┌────────────────────────────────────────────────────────┐")
        print(f"│ After completing these steps, run the script again.    │")
        print(f"└────────────────────────────────────────────────────────┘")
        return False
    
    print("✓ Client secret file found\n")
    
    # Check for API key
    if not check_api_key():
        print(f"⚠  Missing {API_KEY_FILE}!\n")
        print(f"┌────────────────────────────────────────────────────────┐")
        print(f"│ STEP-BY-STEP: Get YouTube API Key                      │")
        print(f"└────────────────────────────────────────────────────────┘\n")
        print("An API Key is needed to read public data from the source")
        print("channel without authentication.\n")
        
        print(f"📋 STEP 1: Go to Google Cloud Console")
        print(f"   → https://console.cloud.google.com/apis/credentials")
        print(f"   → (Use the SAME project where you created OAuth credentials)\n")
        
        print(f"📋 STEP 2: Create API Key")
        print(f"   → Click 'CREATE CREDENTIALS' → 'API key'")
        print(f"   → A popup will show your new API key")
        print(f"   → Click 'COPY' to copy the key\n")
        
        print(f"📋 STEP 3: Restrict API Key (Recommended)")
        print(f"   → Click 'EDIT API KEY' in the popup")
        print(f"   → Under 'API restrictions':")
        print(f"     - Select 'Restrict key'")
        print(f"     - Check only 'YouTube Data API v3'")
        print(f"   → Click 'SAVE'\n")
        
        print(f"📋 STEP 4: Save API Key")
        print(f"   → Create a file named: {os.path.basename(API_KEY_FILE)}")
        print(f"   → Paste your API key in the file (just the key, nothing else)")
        print(f"   → Save it in: {os.path.dirname(API_KEY_FILE)}")
        print(f"   → ⚠️  IMPORTANT: Do NOT commit this file to repositories!\n")
        
        print(f"┌────────────────────────────────────────────────────────┐")
        print(f"│ After creating api_key.txt, run the script again.      │")
        print(f"└────────────────────────────────────────────────────────┘")
        return False
    
    print("✓ API key file found\n")
    
    # Cookies are optional - inform user
    if os.path.exists(COOKIE_FILE):
        print("✓ Cookies file found (will be used for yt-dlp)\n")
    else:
        print("ℹ️  Cookies file not found (will use API fallback if needed)\n")
    
    # Load or create config
    if not os.path.exists(CONFIG_FILE):
        print(f"Creating {CONFIG_FILE}...\n")
        config = create_default_config()
    else:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    
    # Check and prompt for missing fields
    config_updated = False
    
    # Check Channel IDs
    source_id = config.get("source_channel_id", "")
    backup_id = config.get("backup_channel_id", "")
    
    if (not source_id or source_id == "YOUR_SOURCE_CHANNEL_ID_HERE" or
        not backup_id or backup_id == "YOUR_BACKUP_CHANNEL_ID_HERE"):
        source_id, backup_id = prompt_for_channel_ids()
        config["source_channel_id"] = source_id
        config["backup_channel_id"] = backup_id
        config_updated = True
        print(f"\n✓ Channel IDs saved\n")
    else:
        print(f"✓ Source Channel ID: {source_id}")
        print(f"✓ Backup Channel ID: {backup_id}\n")
    
    # Save config if updated
    if config_updated:
        with open(CONFIG_FILE, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=2)
        print(f"✓ Configuration saved to {CONFIG_FILE}\n")
    
    # Verify test user setup before proceeding (only if token doesn't exist yet)
    if not os.path.exists(TOKEN_FILE):
        print(f"{'='*60}")
        print("IMPORTANT: Test User Configuration")
        print(f"{'='*60}\n")
        print("Before authentication, ensure you're added as a test user")
        print("in Google Cloud Console, otherwise you'll get Error 403.\n")
        print("How to add yourself as a test user:")
        print("  1. Go to: https://console.cloud.google.com/apis/credentials/consent")
        print("  2. Click 'EDIT APP' (or navigate to test users section)")
        print("  3. Scroll to 'Test users' → Click 'ADD USERS'")
        print("  4. Enter your email address")
        print("  5. Click 'SAVE'\n")
        
        while True:
            response = input("Have you added yourself as a test user? (yes/no): ").strip().lower()
            if response in ['yes', 'y']:
                print()
                break
            elif response in ['no', 'n']:
                print("\n⚠️ Please add yourself as a test user first, then run again.\n")
                return False
            else:
                print("Please answer 'yes' or 'no'\n")
    else:
        print("✓ Previous authentication found, skipping test user check\n")
    
    print("✓ Configuration complete")
    print(f"\nBackup settings:")
    print(f"  • Source Channel: {config['source_channel_id']}")
    print(f"  • Backup Channel: {config['backup_channel_id']}")
    print(f"  • Dry run mode: {'ENABLED (no uploads)' if DRY_RUN else 'Disabled'}")
    print(f"  • Auto confirm: {'ENABLED (no prompts)' if AUTO_CONFIRM else 'Disabled'}")
    print(f"  • Download method: yt-dlp + {'API fallback' if USE_API_FALLBACK else 'no fallback'}")
    print(f"  • Download delay: {DOWNLOAD_DELAY_SECONDS} seconds between videos")
    print(f"  • Backup mode: {'Full backup (API)' if INITIAL_FULL_BACKUP else 'Incremental (RSS)'}")
    print(f"  • Archive file: {ARCHIVE_FILE}")
    print(f"  • Log file: {LOG_FILE}")
    print(f"  • Download directory: {DOWNLOAD_DIR}")
    print(f"\nAuthentication:")
    print(f"  • OAuth (for backup channel): {CLIENT_SECRET_FILE}")
    print(f"  • API Key (for source channel): {API_KEY_FILE}")
    
    print("\nSetup complete! Starting authentication...\n")
    return True

# =====================================
# CONFIG & STATE UTILITIES
# =====================================

def load_config():
    """Load user configuration from backup_config.json"""
    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        return json.load(file)

def load_archive():
    """Load archive of already processed videos"""
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_to_archive(video_id):
    """Save video ID to archive"""
    with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
        f.write(f"{video_id}\n")

def load_state():
    """Load backup state"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "full_backup_completed": False,
        "last_backup_date": None,
        "total_videos_backed_up": 0
    }

def save_state(state):
    """Save backup state"""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

# =====================================
# AUTHENTICATION
# =====================================

def authenticate():
    """Authenticate user via OAuth2 and return YouTube service (for backup channel)"""
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

    return build("youtube", "v3", credentials=credentials)

def get_youtube_public_service():
    """Get YouTube service with API key for public data access (for source channel)"""
    api_key = load_api_key()
    if not api_key:
        print("ERROR: API key not found!")
        sys.exit(1)
    return build("youtube", "v3", developerKey=api_key)

# =====================================
# QUOTA TRACKING UTILITIES
# =====================================

def add_quota_cost(cost):
    """Track API quota usage"""
    global quota_used
    quota_used += cost

# =====================================
# YOUTUBE RSS & API LOGIC
# =====================================

def get_channel_videos_rss(channel_id):
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

def get_all_channel_videos_api(channel_id):
    """Retrieve ALL videos from channel via API using public API key (no OAuth needed)"""
    print(f"\n📡 Fetching ALL videos from channel via API...")
    print(f"   Using API key for public data access")
    print(f"   This will use API quota (~1 unit per 50 videos)")
    
    # Get public YouTube service with API key
    youtube_public = get_youtube_public_service()
    
    # Get the channel's "uploads" playlist
    channel_response = youtube_public.channels().list(
        part='contentDetails',
        id=channel_id,
        fields='items(contentDetails/relatedPlaylists/uploads)'
    ).execute()
    add_quota_cost(1)
    
    if not channel_response.get('items'):
        print("⚠  Channel not found!")
        return []
    
    uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    
    # Retrieve all videos from the uploads playlist
    videos = []
    next_page_token = None
    page_count = 0
    
    while True:
        page_count += 1
        print(f"   Fetching page {page_count}...", end='', flush=True)
        
        playlist_response = youtube_public.playlistItems().list(
            part='snippet',
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=next_page_token,
            fields='nextPageToken,items(snippet(resourceId/videoId,title,publishedAt))'
        ).execute()
        add_quota_cost(1)
        
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

def get_backup_channel_videos(youtube_service, channel_id):
    """Retrieve all video titles from the backup channel"""
    print(f"\n📋 Checking videos already present in backup channel...")
    
    # Get the channel's "uploads" playlist
    channel_response = youtube_service.channels().list(
        part='contentDetails',
        id=channel_id,
        fields='items(contentDetails/relatedPlaylists/uploads)'
    ).execute()
    add_quota_cost(1)
    
    if not channel_response.get('items'):
        print("⚠  Backup channel not found!")
        return set()
    
    uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    
    # Retrieve all video titles from the playlist
    backed_up_titles = set()
    next_page_token = None
    
    while True:
        playlist_response = youtube_service.playlistItems().list(
            part='snippet',
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=next_page_token,
            fields='nextPageToken,items(snippet/title)'
        ).execute()
        add_quota_cost(1)
        
        for item in playlist_response.get('items', []):
            title = item['snippet']['title']
            backed_up_titles.add(title)
        
        next_page_token = playlist_response.get('nextPageToken')
        if not next_page_token:
            break
    
    print(f"✓ Found {len(backed_up_titles)} videos in backup channel")
    return backed_up_titles

# =====================================
# VIDEO DOWNLOAD & UPLOAD LOGIC
# =====================================

def download_video_ytdlp(video_url, output_dir):
    """Download video using yt-dlp with improved settings"""
    print(f"   Method: yt-dlp")
    
    ydl_opts = {
        # Try multiple format combinations for better compatibility
        'format': (
            'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/'
            'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/'
            'best'
        ),
        'writeinfojson': True,
        'writethumbnail': True,
        'outtmpl': f'{output_dir}/%(id)s.%(ext)s',
        'quiet': False,
        'no_warnings': False,
        'ignoreerrors': False,
        # Use multiple player clients for better success rate
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web', 'ios'],
                'player_skip': ['webpage', 'configs'],
            }
        },
        # Realistic browser headers
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
        }
    }
    
    # Use cookies if available
    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE
        print(f"   Using cookies from {COOKIE_FILE}")
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            video_id = info['id']
            
            # Find downloaded video file
            video_file = None
            for ext in ['mp4', 'webm', 'mkv', 'mov']:
                potential_file = f"{output_dir}/{video_id}.{ext}"
                if os.path.exists(potential_file):
                    video_file = potential_file
                    break
            
            if not video_file:
                return None
            
            # Find thumbnail file
            thumbnail_file = None
            for ext in ['jpg', 'jpeg', 'png', 'webp']:
                potential_thumb = f"{output_dir}/{video_id}.{ext}"
                if os.path.exists(potential_thumb):
                    thumbnail_file = potential_thumb
                    break
            
            info_file = f"{output_dir}/{video_id}.info.json"
            
            return {
                'video_file': video_file,
                'thumbnail_file': thumbnail_file,
                'info_file': info_file,
                'info': info,
                'success': True,
                'method': 'yt-dlp'
            }
    
    except Exception as e:
        print(f"   yt-dlp failed: {e}")
        return None

def download_video_api(youtube_service, video_id, output_dir):
    """Download video using YouTube API as fallback"""
    print(f"   Method: YouTube API (fallback)")
    
    try:
        import requests
        
        # Get video details from API
        video_response = youtube_service.videos().list(
            part='snippet,contentDetails,status',
            id=video_id,
            fields='items(id,snippet(title,description,tags,thumbnails,categoryId),contentDetails,status)'
        ).execute()
        add_quota_cost(1)
        
        if not video_response.get('items'):
            print(f"   Video not found in API")
            return None
        
        video_data = video_response['items'][0]
        snippet = video_data['snippet']
        
        # Use yt-dlp just to get the direct stream URL (doesn't download)
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'best[ext=mp4]/best',
            'extractor_args': {
                'youtube': {
                    'player_client': ['android'],
                }
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
            
            if not info or 'url' not in info:
                print(f"   Could not extract stream URL")
                return None
            
            stream_url = info['url']
            
            # Download video file
            video_file = f"{output_dir}/{video_id}.mp4"
            print(f"   Downloading video stream...")
            
            response = requests.get(stream_url, stream=True, timeout=300)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(video_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = int((downloaded / total_size) * 100)
                            print(f"\r   Progress: {progress}%", end='', flush=True)
            
            print(f"\r   ✓ Video downloaded ({downloaded / 1024 / 1024:.1f} MB)")
            
            # Download thumbnail
            thumbnail_file = None
            thumbnails = snippet.get('thumbnails', {})
            thumbnail_url = None
            
            # Try to get best quality thumbnail
            for quality in ['maxres', 'standard', 'high', 'medium', 'default']:
                if quality in thumbnails:
                    thumbnail_url = thumbnails[quality]['url']
                    break
            
            if thumbnail_url:
                thumbnail_file = f"{output_dir}/{video_id}.jpg"
                try:
                    thumb_response = requests.get(thumbnail_url, timeout=30)
                    thumb_response.raise_for_status()
                    with open(thumbnail_file, 'wb') as f:
                        f.write(thumb_response.content)
                    print(f"   ✓ Thumbnail downloaded")
                except Exception as e:
                    print(f"   ⚠ Thumbnail download failed: {e}")
                    thumbnail_file = None
            
            # Save info as JSON
            info_file = f"{output_dir}/{video_id}.info.json"
            info_data = {
                'id': video_id,
                'title': snippet.get('title'),
                'description': snippet.get('description'),
                'tags': snippet.get('tags', []),
                'category_id': snippet.get('categoryId'),
                'thumbnails': snippet.get('thumbnails'),
                'channel': snippet.get('channelTitle'),
                'channel_id': snippet.get('channelId'),
            }
            
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(info_data, f, indent=2, ensure_ascii=False)
            
            return {
                'video_file': video_file,
                'thumbnail_file': thumbnail_file,
                'info_file': info_file,
                'info': info_data,
                'success': True,
                'method': 'api'
            }
    
    except Exception as e:
        print(f"   API download failed: {e}")
        return None

def download_video(youtube_service, video_url, output_dir):
    """Download video with yt-dlp and API fallback"""
    print(f"\n⬇️  Downloading video...")
    
    # Extract video ID from URL
    video_id = video_url.split('watch?v=')[-1].split('&')[0]
    
    # Try yt-dlp first
    result = download_video_ytdlp(video_url, output_dir)
    
    # If yt-dlp failed and API fallback is enabled, try API
    if not result and USE_API_FALLBACK:
        print(f"\n   Trying API fallback...")
        result = download_video_api(youtube_service, video_id, output_dir)
    
    if not result:
        print(f"\n   ❌ All download methods failed")
        return {
            'video_file': None,
            'thumbnail_file': None,
            'info_file': None,
            'info': {},
            'success': False,
            'method': None
        }
    
    print(f"   ✓ Download successful via {result['method']}")
    return result

def upload_video(youtube_service, video_data):
    """Upload video to YouTube with original metadata (or simulate in dry run)"""
    if DRY_RUN:
        print(f"\n⬆️  [DRY RUN] Would upload video to backup channel...")
        print(f"   Title: {video_data['info'].get('title', 'Untitled')}")
        print(f"✓ [DRY RUN] Upload simulated successfully!")
        return "DRY_RUN_VIDEO_ID"
    
    print(f"\n⬆️  Uploading video to backup channel...")
    
    info = video_data['info']
    video_file = video_data['video_file']
    thumbnail_file = video_data['thumbnail_file']
    
    # Prepare metadata (handle both yt-dlp and API info formats)
    title = info.get('title', 'Untitled')
    description = info.get('description', '')
    tags = info.get('tags', [])
    category_id = str(info.get('category_id') or info.get('categoryId', '22'))
    
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags if tags else [],
            'categoryId': category_id
        },
        'status': {
            'privacyStatus': 'private',
            'selfDeclaredMadeForKids': False
        }
    }
    
    # Upload video
    media = MediaFileUpload(video_file, chunksize=-1, resumable=True)  # type: ignore[arg-type]
    
    request = youtube_service.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )
    add_quota_cost(1600)
    
    response = None
    print("   Uploading...", end='', flush=True)
    
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            print(f"\r   Uploading... {progress}%", end='', flush=True)
    
    print(f"\r✓ Video uploaded successfully! ID: {response['id']}")
    
    # Upload thumbnail if available
    if thumbnail_file and os.path.exists(thumbnail_file):
        try:
            print("   Uploading thumbnail...", end='', flush=True)
            youtube_service.thumbnails().set(
                videoId=response['id'],
                media_body=MediaFileUpload(thumbnail_file)  # type: ignore[arg-type]
            ).execute()
            add_quota_cost(50)
            print("\r✓ Thumbnail uploaded successfully!")
        except Exception as e:
            print(f"\r⚠  Error uploading thumbnail: {e}")
    
    return response['id']

def cleanup_files(video_data):
    """Remove temporary files"""
    files_to_remove = [
        video_data.get('video_file'),
        video_data.get('thumbnail_file'),
        video_data.get('info_file')
    ]
    
    for file in files_to_remove:
        if file and os.path.exists(file):
            try:
                os.remove(file)
            except Exception as e:
                print(f"⚠  Error removing file {file}: {e}")

# =====================================
# MAIN EXECUTION LOGIC
# =====================================

def run():
    """Main execution function"""
    global quota_used
    quota_used = 0
    
    print("╔═══════════════════════════════════════╗")
    print("║  YouTube Automatic Backup Script      ║")
    print("╚═══════════════════════════════════════╝\n")
    
    # Load configuration
    config = load_config()
    
    # Load state
    state = load_state()
    
    # Create download directory
    Path(DOWNLOAD_DIR).mkdir(exist_ok=True)
    
    # Authenticate with YouTube API
    print("🔐 Authenticating...")
    youtube_service = authenticate()
    print("✓ Authentication completed")
    
    # Load archive
    archive = load_archive()
    print(f"✓ Archive loaded ({len(archive)} videos already backed up)")
    
    # Determine backup mode
    use_full_backup = INITIAL_FULL_BACKUP and not state.get("full_backup_completed", False)
    
    if use_full_backup:
        print(f"\n{'='*60}")
        print(f"🔹 FULL BACKUP MODE - First time complete backup")
        print(f"{'='*60}")
        print(f"This will retrieve ALL videos from the source channel via API")
        print(f"Using API key (no OAuth needed for public source channel)")
        print(f"Estimated quota cost: ~1 unit per 50 videos")
        print(f"After completion, future runs will use RSS (free)\n")
        
        if not AUTO_CONFIRM:
            response = input("Proceed with full backup? (y/n): ").lower()
            if response != 'y':
                print("Full backup cancelled. Set INITIAL_FULL_BACKUP = False to use RSS mode.")
                return
        
        # Get ALL videos via API (using API key for public access)
        source_videos = get_all_channel_videos_api(config['source_channel_id'])
    else:
        print(f"\n{'='*60}")
        print(f"🔹 INCREMENTAL MODE - Checking recent videos via RSS")
        print(f"{'='*60}")
        print(f"Checking for new videos (last ~15 from RSS feed)")
        print(f"No API quota will be used for video discovery\n")
        
        # Get recent videos via RSS
        source_videos = get_channel_videos_rss(config['source_channel_id'])

    print(f"\n{'='*60}")
    print(f"🔹 Found {len(source_videos)} total videos")
    print(f"{'='*60}\n")

    # Retrieve videos already present in backup channel
    backed_up_titles = get_backup_channel_videos(youtube_service, config['backup_channel_id'])
    
    # Filter videos to backup
    videos_to_backup = []
    for video in source_videos:
        if video['id'] not in archive and video['title'] not in backed_up_titles:
            videos_to_backup.append(video)
    
    if not videos_to_backup:
        print("\n✓ All videos have already been backed up!")
        print("   No action needed.")
        
        # Mark full backup as completed if in full backup mode
        if use_full_backup:
            state["full_backup_completed"] = True
            state["last_backup_date"] = datetime.now().isoformat()
            save_state(state)
            print("\n✓ Full backup marked as completed!")
            print("   Future runs will use RSS for incremental updates.")
        
        return
    
    print(f"\n{'='*60}")
    print(f"🔹 Found {len(videos_to_backup)} videos to backup")
    print(f"{'='*60}\n")
    
    # Sort by publish date (oldest first for full backup, newest first for incremental)
    if use_full_backup:
        videos_to_backup.sort(key=lambda x: x['published'])
        print("Backing up in chronological order (oldest first)...\n")
    else:
        videos_to_backup.sort(key=lambda x: x['published'], reverse=True)
        print("Backing up in reverse chronological order (newest first)...\n")
    
    for idx, video in enumerate(videos_to_backup, 1):
        print(f"{idx}/{len(videos_to_backup)}. {video['title']}")
        print(f"   URL: {video['url']}")
        print(f"   Published: {video['published']}\n")
    
    # Process each video
    videos_backed_up = 0
    
    for idx, video in enumerate(videos_to_backup, 1):
        print(f"\n{'─'*60}")
        print(f"🔹 Video {idx}/{len(videos_to_backup)}: {video['title']}")
        print(f"{'─'*60}")
        
        # Ask for confirmation unless AUTO_CONFIRM is enabled
        if not AUTO_CONFIRM:
            response = input(f"\n❓ Proceed with backing up this video? (y/n/q to quit): ").lower()
            
            if response == 'q':
                print("\n👋 Operation interrupted by user.")
                break
            
            if response != 'y':
                print("⏭️  Video skipped.")
                continue
        
        try:
            # Add delay between downloads to avoid rate limiting
            if videos_backed_up > 0 and DOWNLOAD_DELAY_SECONDS > 0:
                print(f"\n⏳ Waiting {DOWNLOAD_DELAY_SECONDS} seconds before next download...")
                time.sleep(DOWNLOAD_DELAY_SECONDS)
            
            # Download video
            video_data = download_video(youtube_service, video['url'], DOWNLOAD_DIR)
            
            if not video_data['success'] or not video_data['video_file']:
                print("⚠  Error: video file not found after download")
                continue
            
            # Upload video
            uploaded_video_id = upload_video(youtube_service, video_data)
            
            # Save to archive
            save_to_archive(video['id'])
            
            # Log the backup
            log_backed_up_video(
                video['id'],
                video['title'],
                video_data['info'].get('channel', 'Unknown Channel'),
                uploaded_video_id
            )
            
            # Cleanup
            print("\n🧹 Cleaning up temporary files...")
            cleanup_files(video_data)
            
            print(f"\n✅ Backup completed successfully!")
            videos_backed_up += 1
            
            # Update state
            state["total_videos_backed_up"] = state.get("total_videos_backed_up", 0) + 1
            state["last_backup_date"] = datetime.now().isoformat()
            save_state(state)
            
        except Exception as e:
            print(f"\n❌ Error during backup: {e}")
            if not AUTO_CONFIRM:
                response = input("Continue with the next video? (y/n): ").lower()
                if response != 'y':
                    break
            else:
                print("Auto-continuing to next video...")
    
    # Mark full backup as completed if we processed all videos in full backup mode
    if use_full_backup and videos_backed_up == len(videos_to_backup):
        state["full_backup_completed"] = True
        save_state(state)
        print(f"\n{'='*60}")
        print("🎉 FULL BACKUP COMPLETED!")
        print(f"{'='*60}")
        print(f"✓ All {videos_backed_up} videos have been backed up")
        print(f"✓ Future runs will use RSS for incremental updates (no quota)")
        print(f"✓ To force another full backup, delete: {STATE_FILE}")
    
    # Summary
    print(f"\n{'='*60}")
    print(f"🎉 Backup operation completed!")
    print(f"   Videos backed up this run: {videos_backed_up}")
    print(f"   Total videos backed up: {state.get('total_videos_backed_up', 0)}")
    print(f"   API quota used: {quota_used} units")
    if use_full_backup and videos_backed_up < len(videos_to_backup):
        print(f"   ⚠️  Full backup incomplete - run again to continue")
    print(f"{'='*60}\n")

# =====================================
# ENTRY POINT
# =====================================

if __name__ == '__main__':
    # Check first-run setup
    if not first_run_setup():
        sys.exit(1)
    
    try:
        run()
    except KeyboardInterrupt:
        print("\n\n👋 Operation interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Critical error: {e}")
        sys.exit(1)