import os
import json
import yaml
import time
import xml.etree.ElementTree as ET
import urllib.request
from datetime import datetime, timedelta, timezone
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# =====================================
# GENERAL CONFIGURATION - EDIT THESE VALUES
# =====================================

# Script Behavior
POLL_INTERVAL_MINUTES = 360                             # How often to check for new videos (6 hours to save quota)
MAX_VIDEOS_PER_CHANNEL = 5                              # Max videos to check per channel each time
RETRY_DELAY_MINUTES = 60                                # Wait time after errors before retry (1 hour for quota errors)
INCLUDE_SHORTS = False                                  # Set to True to include YouTube Shorts, False to exclude them
                                                        # Note: Filtering shorts costs +1 API unit per channel (to check video durations)
SHORTS_MAX_DURATION_SECONDS = 90                        # Maximum duration in seconds to consider a video as a Short (default: 90)
USE_RSS_FEEDS = True                                    # Set to True to use RSS feeds (FREE, no quota usage), False to use API
DRY_RUN = False                                         # Set to True to simulate without actually adding videos (no quota for playlist operations)

# Keyword Filtering (case-insensitive)
ENABLE_KEYWORD_FILTER = False                           # Set to True to enable keyword filtering
FILTER_MODE = "include"                                 # "include" = only videos with these keywords, "exclude" = skip videos with these keywords
FILTER_KEYWORDS = []                                    # List of keywords to include/exclude (e.g., ["tutorial", "review"]).

# File Paths
CONFIG_FILE = "config.yaml"                             # User-specific settings (not in repository)
CLIENT_SECRET_FILE = "client_secret.json"               # OAuth credentials file (not in repository)
TOKEN_FILE = "token.json"                               # OAuth token cache (auto-generated)
STATE_FILE = "state.json"                               # Processing state (auto-generated)
LOG_FILE = "added_videos.log"                           # Log of added videos (auto-generated)
SUBSCRIPTIONS_CACHE_FILE = "subscriptions_cache.json"   # Cached subscriptions list (auto-generated)

# Caching Settings
CACHE_SUBSCRIPTIONS_HOURS = 24                          # How long to cache subscriptions list (in hours)

# =====================================
# TECHNICAL CONFIGURATION (DO NOT EDIT)
# =====================================

SCOPES = ["https://www.googleapis.com/auth/youtube"]
POLL_INTERVAL_SECONDS = POLL_INTERVAL_MINUTES * 60
RETRY_DELAY_SECONDS = RETRY_DELAY_MINUTES * 60

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Make all file paths relative to script directory
CONFIG_FILE = os.path.join(SCRIPT_DIR, CONFIG_FILE)
CLIENT_SECRET_FILE = os.path.join(SCRIPT_DIR, CLIENT_SECRET_FILE)
TOKEN_FILE = os.path.join(SCRIPT_DIR, TOKEN_FILE)
STATE_FILE = os.path.join(SCRIPT_DIR, STATE_FILE)
LOG_FILE = os.path.join(SCRIPT_DIR, LOG_FILE)
SUBSCRIPTIONS_CACHE_FILE = os.path.join(SCRIPT_DIR, SUBSCRIPTIONS_CACHE_FILE)

# Global quota tracking
quota_used = 0

# =====================================
# CACHING UTILITIES
# =====================================

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
        age_hours = (now - cached_time).total_seconds() / 3600
        
        if age_hours < CACHE_SUBSCRIPTIONS_HOURS:
            print(f"✓ Using cached subscriptions (age: {age_hours:.1f} hours)")
            return cache_data
        else:
            print(f"⚠ Cache expired (age: {age_hours:.1f} hours), refreshing...")
            return None
            
    except Exception as e:
        print(f"⚠ Cache load error: {e}")
        return None

def save_subscriptions_cache(subscriptions, etag=None):
    """Save subscriptions list to cache"""
    cache_data = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "etag": etag,
        "subscriptions": subscriptions
    }
    
    with open(SUBSCRIPTIONS_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2)
    
    print(f"✓ Subscriptions cached")

# =====================================
# LOGGING UTILITIES
# =====================================

def log_added_video(video_id, video_title, channel_title):
    """Log added video to file and print compact one-line format"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    log_entry = f"[{timestamp}] {channel_title} - {video_title} - {video_url}\n"
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)
    
    print(f"  ✓ {video_title} - {video_url}")

# =====================================
# FIRST RUN SETUP
# =====================================

def create_default_config():
    """Create a default config.yaml file with placeholders"""
    default_config = {
        "youtube": {
            "target_playlist_id": "YOUR_PLAYLIST_ID_HERE"
        }
    }
    
    with open(CONFIG_FILE, "w") as file:
        yaml.dump(default_config, file, default_flow_style=False, sort_keys=False)
    
    print(f"✓ Created {CONFIG_FILE}")
    return default_config

def check_client_secret():
    """Check if client_secret.json exists"""
    return os.path.exists(CLIENT_SECRET_FILE)

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
        playlist_id = input("Enter your Playlist ID: ").strip()
        if playlist_id and playlist_id != "YOUR_PLAYLIST_ID_HERE":
            return playlist_id
        print("❌ Invalid Playlist ID. Please try again.\n")

def first_run_setup():
    """Guide user through first-run configuration"""
    print("\n" + "="*60)
    print("FIRST RUN SETUP - YouTube Subscription Auto Playlist")
    print("="*60 + "\n")
    
    # Check for client_secret.json first
    if not check_client_secret():
        print(f"⚠ Missing {CLIENT_SECRET_FILE}!\n")
        print(f"┌────────────────────────────────────────────────────────┐")
        print(f"STEP-BY-STEP: Get OAuth 2.0 Credentials")
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
        print(f"   → You may see a new interface 'Google Auth platform'")
        print(f"   → If you see 'Get Started' button, click it")
        print(f"   → If using the new interface:")
        print(f"      • Go to Menu → Google Auth platform → Branding")
        print(f"      • Under 'App Information':")
        print(f"        - App name: (e.g., 'YouTube Subscription Auto Playlist')")
        print(f"        - User support email: (select your email)")
        print(f"      • Go to 'Audience' tab")
        print(f"        - Select 'External' (Esterno)")
        print(f"        - This makes the app available for testing with your Google Account")
        print(f"      • ⚠️ IMPORTANT: Add yourself as a test user")
        print(f"        - Go to 'Test users' section or tab")
        print(f"        - Click 'ADD USERS' or '+ Add users'")
        print(f"        - Enter your email address")
        print(f"        - Click 'SAVE'")
        print(f"      • Click 'SAVE' or 'SAVE AND CONTINUE' to finish")
        print(f"   → If using the old interface:")
        print(f"      • Select 'External' → Click 'CREATE'")
        print(f"      • Fill in App name and User support email")
        print(f"      • Click 'SAVE AND CONTINUE' through screens")
        print(f"      • ⚠️ On 'Test users' screen:")
        print(f"        - Click 'ADD USERS'")
        print(f"        - Enter your email address")
        print(f"        - Click 'ADD' then 'SAVE AND CONTINUE'\n")
        
        print(f"📋 STEP 4: Create OAuth 2.0 Client ID")
        print(f"   → Go to: https://console.cloud.google.com/apis/credentials")
        print(f"   → Click 'CREATE CREDENTIALS' → 'OAuth client ID'")
        print(f"   → Application type: Select 'Desktop app'")
        print(f"   → Name: (e.g., 'YouTube Subscription Auto Playlist')")
        print(f"   → Click 'CREATE'\n")
        
        print(f"📋 STEP 5: Download Credentials")
        print(f"   → In the popup, click 'DOWNLOAD JSON'")
        print(f"   → Or: Go to Credentials page → Click download icon (⬇)")
        print(f"   → Rename the file to: {os.path.basename(CLIENT_SECRET_FILE)}")
        print(f"   → Move it to: {os.path.dirname(CLIENT_SECRET_FILE)}\n")
        
        print(f"┌────────────────────────────────────────────────────────┐")
        print(f"After completing these steps, run the script again.")
        print(f"\n⚠️ TROUBLESHOOTING:")
        print(f"If you see 'Error 403: access_denied' when the browser opens:")
        print(f"  → Go to: Menu > Google Auth platform > Audience")
        print(f"  → Direct link: https://console.cloud.google.com/auth/audience")
        print(f"  → Under 'Test users', click 'Add users'")
        print(f"  → Make sure YOUR EMAIL is added as a test user")
        print(f"  → Wait a few minutes and try again")
        print(f"└────────────────────────────────────────────────────────┘")
        return False
    
    print("✓ Client secret file found\n")
    
    # Load or create config
    if not os.path.exists(CONFIG_FILE):
        print(f"Creating {CONFIG_FILE}...\n")
        config = create_default_config()
    else:
        config = load_config()
    
    # Check and prompt for missing fields
    config_updated = False
    
    # Check Playlist ID
    playlist_id = config.get("youtube", {}).get("target_playlist_id", "")
    if not playlist_id or playlist_id == "YOUR_PLAYLIST_ID_HERE":
        playlist_id = prompt_for_playlist_id()
        if "youtube" not in config:
            config["youtube"] = {}
        config["youtube"]["target_playlist_id"] = playlist_id
        config_updated = True
        print(f"✓ Playlist ID saved\n")
    else:
        print(f"✓ Playlist ID found: {playlist_id}\n")
    
    # Save config if updated
    if config_updated:
        with open(CONFIG_FILE, "w") as file:
            yaml.dump(config, file, default_flow_style=False, sort_keys=False)
        print(f"✓ Configuration saved to {CONFIG_FILE}\n")
    
    # Verify test user setup before proceeding (only if token doesn't exist yet)
    if not os.path.exists(TOKEN_FILE):
        print(f"{'='*60}")
        print("IMPORTANT: Test User Configuration")
        print(f"{'='*60}\n")
        print("Before you can authenticate, you MUST add yourself as a test user")
        print("in the Google Cloud Console, otherwise you'll get Error 403.\n")
        print("How to add yourself as a test user:")
        print("  1. Go to Google Cloud Console")
        print("  2. Navigate to: Menu > Google Auth platform > Audience")
        print("     Direct link: https://console.cloud.google.com/auth/audience")
        print("  3. Under 'Test users' section, click 'Add users'")
        print("  4. Enter your email address")
        print("  5. Click 'SAVE'\n")
        
        while True:
            response = input("Have you added yourself as a test user? (yes/no): ").strip().lower()
            if response in ['yes', 'y']:
                print()
                break
            elif response in ['no', 'n']:
                print("\n⚠️ Please add yourself as a test user first, then run the script again.\n")
                return False
            else:
                print("Please answer 'yes' or 'no'\n")
    else:
        print("✓ Previous authentication found, skipping test user check\n")
    
    print("✓ Configuration complete")
    print(f"\nMonitoring settings:")
    print(f"  • Target Playlist: {config['youtube']['target_playlist_id']}")
    print(f"  • Check interval: {POLL_INTERVAL_MINUTES} minutes ({POLL_INTERVAL_MINUTES // 60} hours)")
    print(f"  • Videos per channel: {MAX_VIDEOS_PER_CHANNEL} latest")
    print(f"  • Include Shorts: {'Yes' if INCLUDE_SHORTS else 'No (filtered out)'}")
    print(f"  • Method: {'RSS Feeds (FREE - no quota)' if USE_RSS_FEEDS else 'API (uses quota)'}")
    print(f"  • Dry run mode: {'ENABLED (no videos will be added)' if DRY_RUN else 'Disabled'}")
    print(f"  • Subscriptions cache: {CACHE_SUBSCRIPTIONS_HOURS} hours")
    print(f"  • Keyword filter: {'ENABLED' if ENABLE_KEYWORD_FILTER else 'Disabled'}")
    if ENABLE_KEYWORD_FILTER and FILTER_KEYWORDS:
        print(f"    - Mode: {FILTER_MODE.upper()}")
        print(f"    - Keywords: {', '.join(FILTER_KEYWORDS)}")
    print(f"  • Log file: {LOG_FILE}")
    
    if not USE_RSS_FEEDS:
        print(f"\n⚠️ QUOTA WARNING:")
        print(f"  YouTube API has a daily limit of 10,000 units.")
        print(f"  Each subscription check costs ~100 units (search operation).")
        if not INCLUDE_SHORTS:
            print(f"  Filtering Shorts adds ~1 unit per channel (videos.list).")
        print(f"  With many subscriptions, you may hit the limit quickly.")
        print(f"  Optimizations enabled:")
        print(f"    • Subscriptions caching (saves ~1-2 units per run)")
        print(f"    • ETag conditional requests (304 Not Modified)")
        print(f"    • Optimized fields parameter (reduces bandwidth)")
        print(f"\n  💡 TIP: Set USE_RSS_FEEDS = True to eliminate quota usage!")
    else:
        print(f"\n✓ RSS mode enabled - No API quota will be used for checking videos!")
        print(f"  Only subscriptions fetch (~1-2 units/day) and playlist operations")
        print(f"  (~50 units per video added) will consume quota.")
        if not INCLUDE_SHORTS:
            print(f"  Note: Filtering Shorts costs 1 unit per channel with recent videos")
    
    print("\nSetup complete! Starting authentication...\n")
    return True

# =====================================
# CONFIG & STATE UTILITIES
# =====================================

def load_config():
    """Load user configuration from config.yaml"""
    with open(CONFIG_FILE, "r") as file:
        return yaml.safe_load(file)

def load_state():
    """Load local state to avoid duplicate processing"""
    if not os.path.exists(STATE_FILE):
        return {
            "last_check_time": None,
            "processed_videos": [],
            "quota_used_today": 0,
            "quota_reset_date": datetime.now(timezone.utc).date().isoformat()
        }
    with open(STATE_FILE, "r") as file:
        state = json.load(file)
        # Ensure quota fields exist for backward compatibility
        if "quota_used_today" not in state:
            state["quota_used_today"] = 0
        if "quota_reset_date" not in state:
            state["quota_reset_date"] = datetime.now(timezone.utc).date().isoformat()
        return state

def save_state(state):
    """Persist state locally"""
    with open(STATE_FILE, "w") as file:
        json.dump(state, file, indent=2)

# =====================================
# AUTHENTICATION
# =====================================

def authenticate():
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
                exit(0)

        with open(TOKEN_FILE, "w") as token_file:
            token_file.write(credentials.to_json())

    return build("youtube", "v3", credentials=credentials)

# =====================================
# QUOTA TRACKING UTILITIES
# =====================================

def add_quota_cost(cost):
    """Track API quota usage"""
    global quota_used
    quota_used += cost

def reset_quota_if_new_day(state):
    """Reset quota counter if it's a new day (YouTube quota resets at midnight Pacific Time)"""
    today = datetime.now(timezone.utc).date().isoformat()
    last_reset = state.get("quota_reset_date", today)
    
    if today != last_reset:
        print(f"New day detected - resetting quota counter (was {state.get('quota_used_today', 0)} units)")
        state["quota_used_today"] = 0
        state["quota_reset_date"] = today
        return True
    return False

# =====================================
# KEYWORD FILTERING UTILITIES
# =====================================

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

# =====================================
# YOUTUBE API LOGIC
# =====================================

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
            maxResults=50,
            pageToken=next_page_token,
            fields="etag,nextPageToken,items(snippet(resourceId/channelId,title))"
        )
        response = request.execute()
        add_quota_cost(1)
        
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

def get_recent_videos_from_channel_rss(youtube_service, channel_id, published_after):
    """Get videos published after a certain time from a channel using RSS feed"""
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    
    try:
        with urllib.request.urlopen(feed_url, timeout=10) as response:
            xml_data = response.read()
        
        # Parse XML
        root = ET.fromstring(xml_data)
        
        # XML namespaces
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt': 'http://www.youtube.com/xml/schemas/2015',
            'media': 'http://search.yahoo.com/mrss/'
        }
        
        videos = []
        video_ids = []
        
        for entry in root.findall('atom:entry', ns):
            # Get video ID
            video_id_elem = entry.find('yt:videoId', ns)
            if video_id_elem is None or video_id_elem.text is None:
                continue
            video_id = video_id_elem.text
            
            # Get title
            title_elem = entry.find('atom:title', ns)
            if title_elem is None or title_elem.text is None:
                continue
            title = title_elem.text
            
            # Get channel title
            channel_elem = entry.find('atom:author/atom:name', ns)
            if channel_elem is None or channel_elem.text is None:
                continue
            channel_title = channel_elem.text
            
            # Get published date
            published_elem = entry.find('atom:published', ns)
            if published_elem is None or published_elem.text is None:
                continue
            published = published_elem.text
            published_dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
            
            # Filter by publish date
            if published_dt >= published_after:
                video_ids.append(video_id)
                videos.append({
                    "video_id": video_id,
                    "title": title,
                    "channel_title": channel_title,
                    "published": published_dt
                })
        
        # Apply keyword filter before checking durations
        if ENABLE_KEYWORD_FILTER and FILTER_KEYWORDS:
            videos = [v for v in videos if matches_keyword_filter(v["title"])]
            video_ids = [v["video_id"] for v in videos]
        
        # If we need to filter shorts and have videos, check durations
        if not INCLUDE_SHORTS and video_ids:
            filtered_videos = []
            
            # QUOTA COST: 1 unit for videos.list operation
            # This is necessary because RSS feeds don't include duration information
            details_request = youtube_service.videos().list(
                part="contentDetails",
                id=",".join(video_ids),
                fields="items(id,contentDetails/duration)"
            )
            details_response = details_request.execute()
            add_quota_cost(1)
            
            # Parse durations and filter out shorts
            duration_map = {}
            for item in details_response.get("items", []):
                video_id = item["id"]
                duration_str = item["contentDetails"]["duration"]
                duration_seconds = parse_duration(duration_str)
                duration_map[video_id] = duration_seconds
            
            # Keep only videos longer than SHORTS_MAX_DURATION_SECONDS
            for video in videos:
                video_id = video["video_id"]
                if video_id in duration_map and duration_map[video_id] > SHORTS_MAX_DURATION_SECONDS:
                    filtered_videos.append(video)
            
            return filtered_videos
        
        return videos
        
    except Exception as e:
        print(f"RSS Error: {e}")
        return []

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
    add_quota_cost(100)
    
    videos = []
    video_ids = []
    
    for item in response.get("items", []):
        video_ids.append(item["id"]["videoId"])
        videos.append({
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "channel_title": item["snippet"]["channelTitle"]
        })
    
    # Apply keyword filter before checking durations
    if ENABLE_KEYWORD_FILTER and FILTER_KEYWORDS:
        videos = [v for v in videos if matches_keyword_filter(v["title"])]
        video_ids = [v["video_id"] for v in videos]
    
    # If we need to filter shorts, get video details to check duration
    if not INCLUDE_SHORTS and video_ids:
        filtered_videos = []
        
        # Get video details (duration, etc.) with optimized fields
        details_request = youtube_service.videos().list(
            part="contentDetails",
            id=",".join(video_ids),
            fields="items(id,contentDetails/duration)"
        )
        details_response = details_request.execute()
        add_quota_cost(1)
        
        # Parse durations and filter out shorts
        duration_map = {}
        for item in details_response.get("items", []):
            video_id = item["id"]
            duration_str = item["contentDetails"]["duration"]
            # Parse ISO 8601 duration (e.g., PT1M30S = 1 min 30 sec)
            duration_seconds = parse_duration(duration_str)
            duration_map[video_id] = duration_seconds
        
        # Filter videos based on duration
        for video in videos:
            video_id = video["video_id"]
            if video_id in duration_map and duration_map[video_id] > SHORTS_MAX_DURATION_SECONDS:
                filtered_videos.append(video)
        
        return filtered_videos
    
    return videos

def parse_duration(duration_str):
    """Parse ISO 8601 duration string to seconds (e.g., PT1M30S -> 90)"""
    import re
    
    # Match pattern: PT(hours)H(minutes)M(seconds)S
    pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
    match = re.match(pattern, duration_str)
    
    if not match:
        return 0
    
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    
    return hours * 3600 + minutes * 60 + seconds

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
        add_quota_cost(50)
        return True
    except Exception as e:
        print(f"  ⚠ Failed to add video: {e}")
        return False

# =====================================
# MAIN EXECUTION LOGIC
# =====================================

def run():
    global quota_used
    
    config = load_config()
    target_playlist_id = config["youtube"]["target_playlist_id"]
    
    youtube_service = authenticate()
    
    # Load state
    state = load_state()
    
    # Reset quota if new day
    reset_quota_if_new_day(state)
    
    # Initialize quota_used from saved state
    quota_used = state.get("quota_used_today", 0)
    
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
        print(f"DRY RUN MODE - No videos will be added to playlist")
    print(f"{'='*60}\n")
    
    # Get all subscriptions
    print("Fetching your subscriptions...")
    subscriptions = get_all_subscriptions(youtube_service)
    print(f"✓ Found {len(subscriptions)} subscriptions\n")
    
    # Sort subscriptions alphabetically by channel title
    subscriptions.sort(key=lambda x: x["channel_title"].lower())
    
    # Track processed videos in this run
    processed_videos = set(state.get("processed_videos", []))
    videos_added_count = 0
    
    # Track if any errors occurred during processing
    processing_error = False
    
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
                print(f"Checking: {channel_title} → No new videos")
                continue
            
            print(f"Checking: {channel_title} → Found {len(videos)} new video(s)")
            
            for video in videos:
                video_id = video["video_id"]
                
                # Skip if already processed
                if video_id in processed_videos:
                    continue
                
                # Apply keyword filter
                if ENABLE_KEYWORD_FILTER and FILTER_KEYWORDS:
                    if not matches_keyword_filter(video["title"]):
                        print(f"  ⊘ Skipped (keyword filter): {video['title']}")
                        continue
                
                # Add video to playlist
                if add_video_to_playlist(youtube_service, target_playlist_id, video_id):
                    log_added_video(video_id, video["title"], video["channel_title"])
                    processed_videos.add(video_id)
                    videos_added_count += 1
                else:
                    processing_error = True
        
        except Exception as e:
            print(f"Checking: {channel_title} → Error: {e}")
            processing_error = True
    
    # Only update timestamp if no errors occurred
    if not processing_error:
        state["last_check_time"] = check_start_time.isoformat()
    else:
        print(f"\n⚠ Errors occurred during processing - timestamp NOT updated")
        print(f"  Videos will be rechecked in the next cycle")
    
    # Always update processed videos list and quota
    state["processed_videos"] = list(processed_videos)[-1000:]  # Keep last 1000 to prevent file growth
    state["quota_used_today"] = quota_used
    save_state(state)
    
    # Calculate remaining quota estimate and quota used in this run
    daily_quota_limit = 10000
    remaining_quota = daily_quota_limit - quota_used
    quota_before_run = state.get("quota_used_today", 0) if "quota_used_today" in state else 0
    quota_this_run = quota_used - quota_before_run
    
    print(f"\n{'='*60}")
    print(f"Check complete! Added {videos_added_count} new video(s) to playlist")
    if not processing_error:
        print(f"Next check will look for videos after: {check_start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    else:
        print(f"Next check will retry videos from: {time_threshold.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"API quota used this run: {quota_this_run} units")
    print(f"Total quota used today: {quota_used} units")
    print(f"Estimated remaining daily quota: {remaining_quota} / {daily_quota_limit} units")
    print(f"{'='*60}\n")

# =====================================
# ENTRY POINT
# =====================================

if __name__ == "__main__":
    # Check first-run setup
    if not first_run_setup():
        exit(1)
    
    # Main loop
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
                print(f"\n⚠️ QUOTA EXCEEDED!")
                print(f"   YouTube API daily limit of 10,000 units reached.")
                print(f"   Quota resets at midnight Pacific Time (PT/PDT).")
                print(f"   Script will retry in {RETRY_DELAY_MINUTES} minutes.")
                print(f"\n   Tips to reduce quota usage:")
                print(f"   • Run the script less frequently (currently every {POLL_INTERVAL_MINUTES // 60} hours)")
                print(f"   • Reduce MAX_VIDEOS_PER_CHANNEL (currently {MAX_VIDEOS_PER_CHANNEL})")
                print(f"   • Consider reducing the number of subscriptions you follow")
                print(f"   • Request quota increase: https://support.google.com/youtube/contact/yt_api_form")
            else:
                print(f"Retrying in {RETRY_DELAY_MINUTES} minutes...")
            
            time.sleep(RETRY_DELAY_SECONDS)