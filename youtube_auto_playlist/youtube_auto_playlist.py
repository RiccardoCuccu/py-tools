#!/usr/bin/env python3
"""
YouTube Subscription Auto Playlist - Monitor YouTube subscriptions and add new videos to a playlist automatically.

Polls subscribed channels at a configurable interval, detects videos published since
the last run, and adds them to a target YouTube playlist via the Data API v3.

Usage:
    python youtube_auto_playlist.py

Notes:
    - With DRY_RUN enabled nothing is added, logged or recorded as processed.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

import pytz
import yaml
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# General configuration (edit these values)

# Script Behavior
POLL_INTERVAL_MINUTES = 60                              # How often to check for new videos (1 hours to save quota)
MAX_VIDEOS_PER_CHANNEL = 5                              # Max videos to check per channel each time
MAX_PROCESSED_VIDEOS = 5000                             # Max video IDs retained in state to prevent file growth
RETRY_DELAY_MINUTES = 60                                # Wait time after errors before retry (1 hour for quota errors)
INCLUDE_SHORTS = False                                  # Set to True to include YouTube Shorts, False to exclude them
                                                        # Note: Filtering shorts costs +1 API unit per channel (to check video durations)
SHORTS_MAX_DURATION_SECONDS = 120                       # Maximum duration in seconds to consider a video as a Short (default: 120)
USE_RSS_FEEDS = True                                    # Set to True to use RSS feeds (FREE, no quota usage), False to use API
DRY_RUN = False                                         # Set to True to simulate without actually adding videos (no quota for playlist operations)
AUTO_DELETE_INVALID_TOKEN = True                        # Set to True to automatically delete invalid token, False to ask user for confirmation

# Keyword Filtering (case-insensitive)
ENABLE_KEYWORD_FILTER = False                           # Set to True to enable keyword filtering
FILTER_MODE = "include"                                 # "include" = only videos with these keywords, "exclude" = skip videos with these keywords
FILTER_KEYWORDS = []                                    # List of keywords to include/exclude (e.g., ["tutorial", "review"]).

# File Paths
CONFIG_DIR = "config"                                   # Configuration subdirectory for all generated files
CONFIG_FILE = "config.yaml"                             # User-specific settings (not in repository)
CLIENT_SECRET_FILE = "client_secret.json"               # OAuth credentials file (not in repository)
TOKEN_FILE = "token.json"                               # OAuth token cache (auto-generated)
STATE_FILE = "state.json"                               # Processing state (auto-generated)
LOG_FILE = "added_videos.log"                           # Log of added videos (auto-generated)
SUBSCRIPTIONS_CACHE_FILE = "subscriptions_cache.json"   # Cached subscriptions list (auto-generated)

# Caching Settings
CACHE_SUBSCRIPTIONS_HOURS = 24                          # How long to cache subscriptions list (in hours)

# Technical configuration (do not edit)

SCOPES = ["https://www.googleapis.com/auth/youtube"]
POLL_INTERVAL_SECONDS = POLL_INTERVAL_MINUTES * 60
RETRY_DELAY_SECONDS = RETRY_DELAY_MINUTES * 60
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60
FEED_FETCH_TIMEOUT_SECONDS = 10
HTTP_NOT_FOUND = 404
DAILY_QUOTA_LIMIT = 10000
PLACEHOLDER_PLAYLIST_ID = "YOUR_PLAYLIST_ID_HERE"
RSS_FEED_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
RSS_NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}

# API quota costs in units (see the YouTube Data API quota calculator)
QUOTA_COST_LIST = 1
QUOTA_COST_SEARCH = 100
QUOTA_COST_PLAYLIST_INSERT = 50
SUBSCRIPTIONS_PAGE_SIZE = 50

# Pacific Time timezone (handles PST/PDT automatically)
PACIFIC_TZ = pytz.timezone('US/Pacific')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(SCRIPT_DIR, CONFIG_DIR)

# Make all file paths relative to config directory
CONFIG_FILE = os.path.join(CONFIG_DIR, CONFIG_FILE)
CLIENT_SECRET_FILE = os.path.join(CONFIG_DIR, CLIENT_SECRET_FILE)
TOKEN_FILE = os.path.join(CONFIG_DIR, TOKEN_FILE)
STATE_FILE = os.path.join(CONFIG_DIR, STATE_FILE)
LOG_FILE = os.path.join(CONFIG_DIR, LOG_FILE)
SUBSCRIPTIONS_CACHE_FILE = os.path.join(CONFIG_DIR, SUBSCRIPTIONS_CACHE_FILE)

# Setup instructions
CLIENT_SECRET_HELP = """\
STEP-BY-STEP: Get OAuth 2.0 Credentials

STEP 1: Create/Select Google Cloud Project
   - Go to: https://console.cloud.google.com/
   - Click 'Select a project' > 'NEW PROJECT'
   - Enter a project name > Click 'CREATE'

STEP 2: Enable YouTube Data API v3
   - Go to: https://console.cloud.google.com/apis/library
   - Search for 'YouTube Data API v3'
   - Click on it > Click 'ENABLE'

STEP 3: Configure OAuth Consent Screen
   - Go to: https://console.cloud.google.com/apis/credentials/consent
   - You may see a new interface 'Google Auth platform'
   - If you see 'Get Started' button, click it
   - If using the new interface:
      * Go to Menu > Google Auth platform > Branding
      * Under 'App Information':
        - App name: (e.g., 'YouTube Subscription Auto Playlist')
        - User support email: (select your email)
      * Go to 'Audience' tab
        - Select 'External'
        - This makes the app available for testing with your Google Account
      * IMPORTANT: Add yourself as a test user
        - Go to 'Test users' section or tab
        - Click 'ADD USERS' or '+ Add users'
        - Enter your email address
        - Click 'SAVE'
      * Click 'SAVE' or 'SAVE AND CONTINUE' to finish
   - If using the old interface:
      * Select 'External' > Click 'CREATE'
      * Fill in App name and User support email
      * Click 'SAVE AND CONTINUE' through screens
      * IMPORTANT: On 'Test users' screen:
        - Click 'ADD USERS'
        - Enter your email address
        - Click 'ADD' then 'SAVE AND CONTINUE'

STEP 4: Create OAuth 2.0 Client ID
   - Go to: https://console.cloud.google.com/apis/credentials
   - Click 'CREATE CREDENTIALS' > 'OAuth client ID'
   - Application type: Select 'Desktop app'
   - Name: (e.g., 'YouTube Subscription Auto Playlist')
   - Click 'CREATE'

STEP 5: Download Credentials
   - In the popup, click 'DOWNLOAD JSON'
   - Or: Go to Credentials page > Click download icon
   - Rename the file to: {file_name}
   - Move it to: {config_dir}

After completing these steps, run the script again.

TROUBLESHOOTING:
If you see 'Error 403: access_denied' when the browser opens:
  - Go to: Menu > Google Auth platform > Audience
  - Direct link: https://console.cloud.google.com/auth/audience
  - Under 'Test users', click 'Add users'
  - Make sure YOUR EMAIL is added as a test user
  - Wait a few minutes and try again
"""

TEST_USER_HELP = """\
Before you can authenticate, you MUST add yourself as a test user
in the Google Cloud Console, otherwise you'll get Error 403.

How to add yourself as a test user:
  1. Go to Google Cloud Console
  2. Navigate to: Menu > Google Auth platform > Audience
     Direct link: https://console.cloud.google.com/auth/audience
  3. Under 'Test users' section, click 'Add users'
  4. Enter your email address
  5. Click 'SAVE'
"""

# Global quota tracking
quota_used = 0


def write_text_atomic(path, text):
    """Write text to path through a temporary file so a crash never leaves a truncated file."""
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as file:
        file.write(text)
    os.replace(tmp_path, path)


def load_subscriptions_cache():
    """Load cached subscriptions list"""
    if not os.path.exists(SUBSCRIPTIONS_CACHE_FILE):
        return None

    try:
        with open(SUBSCRIPTIONS_CACHE_FILE, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

        # Check if cache is still valid
        cached_time = datetime.fromisoformat(cache_data["cached_at"])
        now = datetime.now(timezone.utc)
        age_hours = (now - cached_time).total_seconds() / SECONDS_PER_HOUR

        if age_hours < CACHE_SUBSCRIPTIONS_HOURS and isinstance(cache_data["subscriptions"], list):
            print(f"[OK] Using cached subscriptions (age: {age_hours:.1f} hours)")
            return cache_data
        else:
            print(f"[WARN] Cache expired (age: {age_hours:.1f} hours), refreshing...")
            return None

    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"[WARN] Cache load error: {e}")
        return None


def save_subscriptions_cache(subscriptions, etag=None):
    """Save subscriptions list to cache"""
    cache_data = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "etag": etag,
        "subscriptions": subscriptions
    }

    write_text_atomic(SUBSCRIPTIONS_CACHE_FILE, json.dumps(cache_data, indent=2))

    print("[OK] Subscriptions cached")


def log_added_video(video_id, video_title, channel_title):
    """Log added video to file and print compact one-line format"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    log_entry = f"[{timestamp}] {channel_title} - {video_title} - {video_url}\n"

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)

    print(f"  [OK] {video_title} - {video_url}")


def create_default_config():
    """Create a default config.yaml file with placeholders"""
    default_config = {
        "youtube": {
            "target_playlist_id": PLACEHOLDER_PLAYLIST_ID
        }
    }

    with open(CONFIG_FILE, "w", encoding="utf-8") as file:
        yaml.dump(default_config, file, default_flow_style=False, sort_keys=False)

    print(f"[OK] Created {CONFIG_FILE}")
    return default_config


def check_client_secret():
    """Check if client_secret.json exists"""
    return os.path.exists(CLIENT_SECRET_FILE)


def normalize_playlist_id(value):
    """Return the bare playlist ID, also accepting a pasted playlist URL containing 'list='."""
    value = str(value or "").strip()
    match = re.search(r"[?&]list=([A-Za-z0-9_-]+)", value)
    return match.group(1) if match else value


def get_target_playlist_id(config):
    """Return the configured playlist ID, or raise ValueError if missing or still a placeholder."""
    youtube_section = config.get("youtube")
    raw = youtube_section.get("target_playlist_id") if isinstance(youtube_section, dict) else None
    playlist_id = normalize_playlist_id(raw)
    if not playlist_id or playlist_id == PLACEHOLDER_PLAYLIST_ID:
        raise ValueError(f"youtube.target_playlist_id is not set in {CONFIG_FILE}")
    return playlist_id


def prompt_for_playlist_id():
    """Prompt user for Target Playlist ID"""
    print(f"\n{'='*60}")
    print("PLAYLIST ID REQUIRED")
    print(f"{'='*60}\n")
    print("This is YOUR playlist where videos from your subscriptions")
    print("will be automatically added.\n")
    print("How to find your Playlist ID:")
    print("  1. Go to YouTube and open YOUR playlist")
    print("  2. Look at the URL in your browser")
    print("  3. Copy the ID after 'list='")
    print("     Example: youtube.com/playlist?list=PLxxxxxx")
    print("     The ID is: PLxxxxxx\n")

    while True:
        playlist_id = normalize_playlist_id(input("Enter your Playlist ID: "))
        if playlist_id and playlist_id != PLACEHOLDER_PLAYLIST_ID:
            return playlist_id
        print("[ERROR] Invalid Playlist ID. Please try again.\n")


def first_run_setup():
    """Guide user through first-run configuration"""
    print("\n" + "="*60)
    print("FIRST RUN SETUP - YouTube Subscription Auto Playlist")
    print("="*60 + "\n")

    # Create config directory if it doesn't exist
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
        print(f"[OK] Created configuration directory: {CONFIG_DIR}\n")

    # Check for client_secret.json first
    if not check_client_secret():
        print(f"[WARN] Missing {CLIENT_SECRET_FILE}!\n")
        print(CLIENT_SECRET_HELP.format(
            file_name=os.path.basename(CLIENT_SECRET_FILE), config_dir=CONFIG_DIR
        ))
        return False

    print("[OK] Client secret file found\n")

    # Load or create config
    if not os.path.exists(CONFIG_FILE):
        print(f"Creating {CONFIG_FILE}...\n")
        config = create_default_config()
    else:
        config = load_config()

    # Check and prompt for missing fields
    youtube_section = config.get("youtube")
    if not isinstance(youtube_section, dict):
        youtube_section = {}
        config["youtube"] = youtube_section
    playlist_id = normalize_playlist_id(youtube_section.get("target_playlist_id"))
    if not playlist_id or playlist_id == PLACEHOLDER_PLAYLIST_ID:
        youtube_section["target_playlist_id"] = prompt_for_playlist_id()
        with open(CONFIG_FILE, "w", encoding="utf-8") as file:
            yaml.dump(config, file, default_flow_style=False, sort_keys=False)
        print("[OK] Playlist ID saved\n")
        print(f"[OK] Configuration saved to {CONFIG_FILE}\n")
    else:
        print(f"[OK] Playlist ID found: {playlist_id}\n")

    # Verify test user setup before proceeding (only if token doesn't exist yet)
    if not os.path.exists(TOKEN_FILE):
        print(f"{'='*60}")
        print("IMPORTANT: Test User Configuration")
        print(f"{'='*60}\n")
        print(TEST_USER_HELP)

        while True:
            response = input("Have you added yourself as a test user? (yes/no): ").strip().lower()
            if response in ['yes', 'y']:
                print()
                break
            elif response in ['no', 'n']:
                print("\n[WARN] Please add yourself as a test user first, then run the script again.\n")
                return False
            else:
                print("Please answer 'yes' or 'no'\n")
    else:
        print("[OK] Previous authentication found, skipping test user check\n")

    print("[OK] Configuration complete")
    print("\nMonitoring settings:")
    print(f"  - Configuration directory: {CONFIG_DIR}")
    print(f"  - Target Playlist: {youtube_section['target_playlist_id']}")
    print(f"  - Check interval: {POLL_INTERVAL_MINUTES} minutes")
    print(f"  - Videos per channel: {MAX_VIDEOS_PER_CHANNEL} latest")
    print(f"  - Include Shorts: {'Yes' if INCLUDE_SHORTS else 'No (filtered out)'}")
    print(f"  - Method: {'RSS Feeds (FREE - no quota)' if USE_RSS_FEEDS else 'API (uses quota)'}")
    print(f"  - Dry run mode: {'ENABLED (no videos will be added)' if DRY_RUN else 'Disabled'}")
    print(f"  - Subscriptions cache: {CACHE_SUBSCRIPTIONS_HOURS} hours")
    print(f"  - Keyword filter: {'ENABLED' if ENABLE_KEYWORD_FILTER else 'Disabled'}")
    if ENABLE_KEYWORD_FILTER and FILTER_KEYWORDS:
        print(f"    - Mode: {FILTER_MODE.upper()}")
        print(f"    - Keywords: {', '.join(FILTER_KEYWORDS)}")
    print(f"  - Log file: {os.path.basename(LOG_FILE)}")
    print(f"  - State file: {os.path.basename(STATE_FILE)}")
    print(f"  - Cache file: {os.path.basename(SUBSCRIPTIONS_CACHE_FILE)}")

    if not USE_RSS_FEEDS:
        print("\n[WARN] QUOTA WARNING:")
        print(f"  YouTube API has a daily limit of {DAILY_QUOTA_LIMIT} units.")
        print(f"  Each subscription check costs ~{QUOTA_COST_SEARCH} units (search operation).")
        if not INCLUDE_SHORTS:
            print("  Filtering Shorts adds ~1 unit per channel (videos.list).")
        print("  With many subscriptions, you may hit the limit quickly.")
        print("  Optimizations enabled:")
        print("    - Subscriptions caching (saves ~1-2 units per run)")
        print("    - Optimized fields parameter (reduces bandwidth)")
        print("\n  TIP: Set USE_RSS_FEEDS = True to eliminate quota usage!")
    else:
        print("\n[OK] RSS mode enabled - No API quota will be used for checking videos!")
        print("  Only subscriptions fetch (~1-2 units/day) and playlist operations")
        print(f"  (~{QUOTA_COST_PLAYLIST_INSERT} units per video added) will consume quota.")
        if not INCLUDE_SHORTS:
            print("  Note: Filtering Shorts costs 1 unit per channel with recent videos")

    print("\nSetup complete! Starting authentication...\n")
    return True


def load_config() -> Dict[str, Any]:
    """Load user configuration from config.yaml"""
    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
        return raw if isinstance(raw, dict) else {}


def load_state():
    """Load local state to avoid duplicate processing"""
    if not os.path.exists(STATE_FILE):
        return {
            "last_check_time": None,
            "processed_videos": [],
            "quota_used_today": 0,
            "quota_reset_date": datetime.now(PACIFIC_TZ).date().isoformat()
        }
    with open(STATE_FILE, "r", encoding="utf-8") as file:
        state = json.load(file)
        # Ensure quota fields exist for backward compatibility
        if "quota_used_today" not in state:
            state["quota_used_today"] = 0
        if "quota_reset_date" not in state:
            state["quota_reset_date"] = datetime.now(PACIFIC_TZ).date().isoformat()
        return state


def save_state(state):
    """Persist state locally (atomically, so an interrupted write cannot corrupt it)"""
    write_text_atomic(STATE_FILE, json.dumps(state, indent=2))


def trim_processed_videos(video_ids: Iterable[str], limit: int = MAX_PROCESSED_VIDEOS) -> List[str]:
    """Deduplicate video IDs preserving insertion order, keeping only the most recent `limit` entries."""
    if limit <= 0:
        return []
    unique_ids = list(dict.fromkeys(video_ids))
    return unique_ids[-limit:]


def load_credentials():
    """Load saved OAuth credentials, or return None if the token file is missing or unreadable"""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        return Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    except (ValueError, OSError) as load_error:
        # A truncated or foreign token would otherwise fail every cycle forever
        print(f"[WARN] Token file unreadable ({load_error}); starting fresh authentication")
        return None


def authenticate():
    """Authenticate user via OAuth2 and return YouTube service"""
    credentials = load_credentials()

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except RefreshError as refresh_error:
                # Check if it's an invalid_grant error
                error_message = str(refresh_error)
                if "invalid_grant" in error_message.lower():
                    print(f"\n[WARN] Token refresh failed: {refresh_error}")
                    print("[WARN] The authentication token is corrupted or has been revoked.\n")

                    should_delete = AUTO_DELETE_INVALID_TOKEN

                    if not AUTO_DELETE_INVALID_TOKEN:
                        # Ask user for confirmation
                        print("The token file needs to be deleted to proceed with a fresh authentication.")
                        print(f"Token file location: {TOKEN_FILE}\n")
                        while True:
                            response = input("Do you want to delete the token file and re-authenticate? (yes/no): ").strip().lower()
                            if response in ['yes', 'y']:
                                should_delete = True
                                break
                            elif response in ['no', 'n']:
                                print("\n[ERROR] Authentication cancelled. Cannot proceed without valid token.")
                                sys.exit(1)
                            else:
                                print("Please answer 'yes' or 'no'\n")

                    if should_delete:
                        print("[OK] Removing corrupted token file...")
                        try:
                            os.remove(TOKEN_FILE)
                            print("[OK] Token file deleted successfully")
                            print("[OK] Starting fresh authentication...\n")
                            credentials = None
                        except OSError as delete_error:
                            print(f"[ERROR] Failed to delete token file: {delete_error}")
                            raise
                else:
                    # Re-raise if it's a different error
                    raise
        else:
            # Invalid and not refreshable (e.g. no refresh token): a fresh login is the only way out
            credentials = None

        # If credentials is None (either fresh start or after invalid_grant), do full auth flow
        if not credentials:
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CLIENT_SECRET_FILE,
                    SCOPES
                )
                credentials = flow.run_local_server(port=8080, open_browser=False)
            except KeyboardInterrupt:
                print("\n\nAuthentication cancelled by user")
                sys.exit(0)

        write_text_atomic(TOKEN_FILE, credentials.to_json())

    return build("youtube", "v3", credentials=credentials)


def add_quota_cost(cost):
    """Track API quota usage"""
    global quota_used
    quota_used += cost


def reset_quota_if_new_day(state):
    """Reset quota counter if it's a new day (YouTube quota resets at midnight Pacific Time)"""
    # Get current time in Pacific timezone
    now_pacific = datetime.now(PACIFIC_TZ)
    current_date_pacific = now_pacific.date().isoformat()

    # Get last reset date (stored as Pacific date)
    last_reset = state.get("quota_reset_date", current_date_pacific)

    # Check if we've crossed midnight Pacific Time
    if current_date_pacific != last_reset:
        print("[INFO] New day detected in Pacific Time - resetting quota counter")
        print(f"   (was {state.get('quota_used_today', 0)} units)")
        state["quota_used_today"] = 0
        state["quota_reset_date"] = current_date_pacific
        return True
    return False


def matches_keyword_filter(title):
    """Check if video title matches keyword filter rules"""
    if not ENABLE_KEYWORD_FILTER or not FILTER_KEYWORDS:
        return True

    title_lower = title.lower()

    if FILTER_MODE == "include":
        # Include mode: video must contain at least one keyword
        return any(keyword.lower() in title_lower for keyword in FILTER_KEYWORDS)
    elif FILTER_MODE == "exclude":
        # Exclude mode: video must NOT contain any keyword
        return not any(keyword.lower() in title_lower for keyword in FILTER_KEYWORDS)
    else:
        # Invalid mode, default to accepting all
        return True


def get_all_subscriptions(youtube_service):
    """Get all channel IDs from user's subscriptions with caching and ETag support"""

    # Try to load from cache first
    cache = load_subscriptions_cache()
    if cache:
        # Use the cache if it's valid
        return cache["subscriptions"]

    # Fetch fresh subscriptions with optimized fields
    print("Fetching subscriptions from API...")
    subscriptions = []
    next_page_token = None
    etag = None

    while True:
        request = youtube_service.subscriptions().list(
            part="snippet",
            mine=True,
            maxResults=SUBSCRIPTIONS_PAGE_SIZE,
            pageToken=next_page_token,
            fields="etag,nextPageToken,items(snippet(resourceId/channelId,title))"
        )
        response = request.execute()
        add_quota_cost(QUOTA_COST_LIST)

        # Save ETag from first response
        if not etag:
            etag = response.get("etag")

        for item in response.get("items", []):
            channel_id = item["snippet"]["resourceId"]["channelId"]
            channel_title = item["snippet"]["title"]
            subscriptions.append({"channel_id": channel_id, "channel_title": channel_title})

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    # Save to cache
    save_subscriptions_cache(subscriptions, etag)

    return subscriptions


def parse_duration(duration_str):
    """Parse ISO 8601 duration string to seconds (e.g., PT1M30S -> 90, P1DT2H -> 93600)"""
    pattern = r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$'
    match = re.match(pattern, duration_str or "")

    if not match:
        return 0

    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    seconds = int(match.group(4) or 0)

    return days * SECONDS_PER_DAY + hours * SECONDS_PER_HOUR + minutes * SECONDS_PER_MINUTE + seconds


def apply_keyword_filter(videos):
    """Return only the videos whose title passes the configured keyword filter"""
    if not (ENABLE_KEYWORD_FILTER and FILTER_KEYWORDS):
        return videos
    return [v for v in videos if matches_keyword_filter(v["title"])]


def filter_out_shorts(youtube_service, videos):
    """Drop videos not longer than SHORTS_MAX_DURATION_SECONDS (costs 1 quota unit per call)"""
    if not videos:
        return videos

    # QUOTA COST: 1 unit for videos.list operation; feeds and search do not expose durations
    details_response = youtube_service.videos().list(
        part="contentDetails",
        id=",".join(v["video_id"] for v in videos),
        fields="items(id,contentDetails/duration)"
    ).execute()
    add_quota_cost(QUOTA_COST_LIST)

    duration_map = {
        item["id"]: parse_duration(item["contentDetails"]["duration"])
        for item in details_response.get("items", [])
    }

    return [
        v for v in videos
        if duration_map.get(v["video_id"], 0) > SHORTS_MAX_DURATION_SECONDS
    ]


def parse_rss_feed(xml_data, published_after):
    """Parse a YouTube channel Atom feed and return videos published at or after published_after"""
    root = ET.fromstring(xml_data)
    videos = []

    for entry in root.findall('atom:entry', RSS_NAMESPACES):
        video_id = entry.findtext('yt:videoId', namespaces=RSS_NAMESPACES)
        title = entry.findtext('atom:title', namespaces=RSS_NAMESPACES)
        channel_title = entry.findtext('atom:author/atom:name', namespaces=RSS_NAMESPACES)
        published = entry.findtext('atom:published', namespaces=RSS_NAMESPACES)
        if not (video_id and title and channel_title and published):
            continue

        try:
            published_dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
        except ValueError:
            continue

        if published_dt >= published_after:
            videos.append({
                "video_id": video_id,
                "title": title,
                "channel_title": channel_title,
                "published": published_dt
            })

    return videos


def get_recent_videos_from_channel_rss(youtube_service, channel_id, published_after):
    """Get videos published after a certain time from a channel using RSS feed

    A missing feed (HTTP 404, e.g. a terminated channel) yields no videos. Any other
    failure propagates so the caller does not advance the last-check timestamp past
    videos that were never seen.
    """
    feed_url = RSS_FEED_URL_TEMPLATE.format(channel_id=channel_id)

    try:
        with urllib.request.urlopen(feed_url, timeout=FEED_FETCH_TIMEOUT_SECONDS) as response:
            xml_data = response.read()
    except urllib.error.HTTPError as http_error:
        if http_error.code == HTTP_NOT_FOUND:
            print(f"[WARN] RSS feed not found for channel {channel_id}")
            return []
        raise

    # Apply keyword filter before checking durations
    videos = apply_keyword_filter(parse_rss_feed(xml_data, published_after))

    if not INCLUDE_SHORTS:
        videos = filter_out_shorts(youtube_service, videos)

    return videos


def get_recent_videos_from_channel(youtube_service, channel_id, published_after):
    """Get videos published after a certain time from a channel using API"""
    request = youtube_service.search().list(
        part="snippet",
        channelId=channel_id,
        type="video",
        order="date",
        publishedAfter=published_after,
        maxResults=MAX_VIDEOS_PER_CHANNEL,
        fields="items(id/videoId,snippet(title,channelTitle))"
    )
    response = request.execute()
    add_quota_cost(QUOTA_COST_SEARCH)

    videos = [
        {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "channel_title": item["snippet"]["channelTitle"]
        }
        for item in response.get("items", [])
    ]

    # Apply keyword filter before checking durations
    videos = apply_keyword_filter(videos)

    if not INCLUDE_SHORTS:
        videos = filter_out_shorts(youtube_service, videos)

    return videos


def add_video_to_playlist(youtube_service, target_playlist_id, video_id):
    """Add a video to the target playlist (or simulate in dry run mode)"""
    if DRY_RUN:
        # Simulate success without making API call
        return True

    try:
        youtube_service.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": target_playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }
        ).execute()
        add_quota_cost(QUOTA_COST_PLAYLIST_INSERT)
        return True
    except Exception as e:
        print(f"  [WARN] Failed to add video: {e}")
        return False


def process_channel_videos(youtube_service, target_playlist_id, videos, processed_videos):
    """Add each unseen video to the playlist, recording successes. Return (added_count, had_error)"""
    added_count = 0
    had_error = False

    for video in videos:
        video_id = video["video_id"]

        # Skip if already processed
        if video_id in processed_videos:
            continue

        # Apply keyword filter
        if not matches_keyword_filter(video["title"]):
            print(f"  [SKIP] Skipped (keyword filter): {video['title']}")
            continue

        if not add_video_to_playlist(youtube_service, target_playlist_id, video_id):
            had_error = True
            continue

        if DRY_RUN:
            # Dry run must not mark videos as seen, or they would never be added later
            print(f"  [DRY RUN] Would add: {video['title']} (https://www.youtube.com/watch?v={video_id})")
        else:
            log_added_video(video_id, video["title"], video["channel_title"])
            processed_videos[video_id] = None
        added_count += 1

    return added_count, had_error


def run():
    """Main execution function for checking and adding videos"""
    global quota_used

    config = load_config()
    target_playlist_id = get_target_playlist_id(config)

    youtube_service = authenticate()

    # Load state
    state = load_state()

    # Reset quota if new day
    reset_quota_if_new_day(state)

    # Initialize quota_used from saved state
    quota_used = state.get("quota_used_today", 0)

    # Save quota value before API calls
    quota_before_run = quota_used

    # Calculate time threshold BEFORE starting the check
    check_start_time = datetime.now(timezone.utc)

    if state.get("last_check_time"):
        # Use last check time
        time_threshold = datetime.fromisoformat(state["last_check_time"])
    else:
        # First run: check videos from the last POLL_INTERVAL_MINUTES
        time_threshold = check_start_time - timedelta(minutes=POLL_INTERVAL_MINUTES)

    published_after = time_threshold.isoformat()

    print(f"\n{'='*60}")
    print(f"Checking for new videos since: {time_threshold.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if DRY_RUN:
        print("DRY RUN MODE - No videos will be added to playlist")
    print(f"{'='*60}\n")

    # Get all subscriptions
    print("Fetching your subscriptions...")
    subscriptions = get_all_subscriptions(youtube_service)
    print(f"[OK] Found {len(subscriptions)} subscriptions\n")

    # Sort subscriptions alphabetically by channel title
    subscriptions.sort(key=lambda x: x["channel_title"].lower())

    # Track processed videos in this run
    # dict preserves insertion order and gives O(1) membership, unlike set
    processed_videos: Dict[str, None] = dict.fromkeys(state.get("processed_videos", []))
    videos_added_count = 0

    # Track if any errors occurred during processing
    processing_error = False

    try:
        # Check each subscription for new videos
        for sub in subscriptions:
            channel_id = sub["channel_id"]
            channel_title = sub["channel_title"]

            try:
                # Use RSS or API based on configuration
                if USE_RSS_FEEDS:
                    videos = get_recent_videos_from_channel_rss(youtube_service, channel_id, time_threshold)
                else:
                    videos = get_recent_videos_from_channel(youtube_service, channel_id, published_after)

                if not videos:
                    print(f"Checking: {channel_title} - No new videos")
                    continue

                print(f"Checking: {channel_title} - Found {len(videos)} new video(s)")

                added, had_error = process_channel_videos(
                    youtube_service, target_playlist_id, videos, processed_videos
                )
                videos_added_count += added
                processing_error = processing_error or had_error

            except Exception as e:
                print(f"Checking: {channel_title} - Error: {e}")
                processing_error = True
    finally:
        # Persist ids and quota even when the loop is interrupted, so videos already
        # added to the playlist are not added again after a restart
        if not DRY_RUN:
            state["processed_videos"] = trim_processed_videos(processed_videos)
        state["quota_used_today"] = quota_used
        save_state(state)

    # Only advance the timestamp if no errors occurred (and never in dry run)
    if processing_error:
        print("\n[WARN] Errors occurred during processing - timestamp NOT updated")
        print("  Videos will be rechecked in the next cycle")
    elif not DRY_RUN:
        state["last_check_time"] = check_start_time.isoformat()
        save_state(state)

    # Calculate remaining quota estimate and quota used in this run
    remaining_quota = DAILY_QUOTA_LIMIT - quota_used
    quota_this_run = quota_used - quota_before_run

    print(f"\n{'='*60}")
    print(f"Check complete! Added {videos_added_count} new video(s) to playlist")
    if not processing_error and not DRY_RUN:
        print(f"Next check will look for videos after: {check_start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    else:
        print(f"Next check will retry videos from: {time_threshold.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"API quota used this run: {quota_this_run} units")
    print(f"Total quota used today: {quota_used} units")
    print(f"Estimated remaining daily quota: {remaining_quota} / {DAILY_QUOTA_LIMIT} units")
    print(f"{'='*60}\n")


def main():
    """Run first-run setup, then check for new videos in an endless loop"""
    if not first_run_setup():
        sys.exit(1)

    while True:
        try:
            run()
            print(f"Next check in {POLL_INTERVAL_MINUTES} minutes...\n")
            time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("\n\nScript stopped by user")
            break
        except Exception as e:
            error_message = str(e)
            print(f"\nError occurred: {e}")

            # Check if it's a quota error
            if "quotaExceeded" in error_message or "quota" in error_message.lower():
                print("\n[WARN] QUOTA EXCEEDED!")
                print(f"   YouTube API daily limit of {DAILY_QUOTA_LIMIT} units reached.")
                print("   Quota resets at midnight Pacific Time (PT/PDT).")
                print(f"   Script will retry in {RETRY_DELAY_MINUTES} minutes.")
                print("\n   Tips to reduce quota usage:")
                print(f"   - Run the script less frequently (currently every {POLL_INTERVAL_MINUTES} minutes)")
                print(f"   - Reduce MAX_VIDEOS_PER_CHANNEL (currently {MAX_VIDEOS_PER_CHANNEL})")
                print("   - Consider reducing the number of subscriptions you follow")
                print("   - Request quota increase: https://support.google.com/youtube/contact/yt_api_form")
            else:
                print(f"Retrying in {RETRY_DELAY_MINUTES} minutes...")

            time.sleep(RETRY_DELAY_SECONDS)


if __name__ == "__main__":
    main()
