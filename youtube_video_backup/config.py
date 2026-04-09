#!/usr/bin/env python3
"""
Configuration and Setup Module
Handles all configuration settings and first-run setup wizard
"""

import os
import json
import sys

# ---------------------------------------------------------------------------
# GENERAL CONFIGURATION - EDIT THESE VALUES
# ---------------------------------------------------------------------------

# Script Behavior
DRY_RUN = False                                         # Set to True to simulate without actually uploading videos
AUTO_CONFIRM = False                                    # Set to True to skip confirmation prompts for each video
USE_API_FALLBACK = True                                 # Set to True to use YouTube API if yt-dlp fails
DOWNLOAD_DELAY_SECONDS = 2                              # Delay between downloads to avoid rate limiting
INITIAL_FULL_BACKUP = True                              # Set to True to do full channel backup via API (first run only)
                                                        # After first complete backup, set to False or delete state.json to trigger again
DELETE_AFTER_UPLOAD = False                             # Set to True to delete video files after successful upload
REQUIRE_NATIVE_QUALITY = True                           # Set to True to abort if video cannot be downloaded at native quality (720p+)
                                                        # If False, will download at any available quality
UPLOAD_CHUNK_SIZE_MB = 50                               # Upload chunk size in MB (default: 50MB)
                                                        # Smaller chunks = more resilient to network issues
                                                        # Larger chunks = faster upload on stable connections
                                                        # Set to -1 to upload entire file in one chunk (not recommended for large files)
VIDEO_PRIVACY_STATUS = "unlisted"                       # Privacy status for uploaded videos: "private", "unlisted", or "public"
                                                        # Default: "unlisted" (video not listed but accessible via link)
SOCKET_TIMEOUT_SECONDS = 60                             # Seconds before a network read is considered timed out
                                                        # yt-dlp default is 20 - increase for slow CDN edges
DOWNLOAD_RETRIES = 15                                   # Max number of overall download retries per video
FRAGMENT_RETRIES = 25                                   # Max retries for each individual fragment
                                                        # Higher values help with flaky CDN connections

# ---------------------------------------------------------------------------
# TECHNICAL CONFIGURATION (DO NOT EDIT)
# ---------------------------------------------------------------------------

# OAuth Scopes
SCOPES = ['https://www.googleapis.com/auth/youtube.upload',
          'https://www.googleapis.com/auth/youtube.readonly']

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuration subdirectory for all generated files
CONFIG_DIR = os.path.join(SCRIPT_DIR, 'config')

# File Paths - all config files go in CONFIG_DIR, downloads in DOWNLOAD_DIR
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")               # User-specific settings (not in repository)
CLIENT_SECRET_FILE = os.path.join(CONFIG_DIR, "client_secret.json") # OAuth credentials file (not in repository)
TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")                 # OAuth token cache (auto-generated)
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")                 # Backup state tracker (auto-generated)
ARCHIVE_FILE = os.path.join(CONFIG_DIR, "archive.txt")              # Archive of processed videos (auto-generated)
LOG_FILE = os.path.join(CONFIG_DIR, "log.txt")                      # Log of backed up videos (auto-generated)
API_KEY_FILE = os.path.join(CONFIG_DIR, "api_key.txt")              # YouTube API key for public data access (not in repository)
CHANNEL_VIDEOS_FILE = os.path.join(CONFIG_DIR, "channel_videos.json") # Complete channel video cache (auto-generated)
DOWNLOAD_DIR = os.path.join(SCRIPT_DIR, 'downloads')                # Downloads stay in root

class Config:
    """Configuration manager"""
    
    def __init__(self, data):
        self.source_channel_id = data.get('source_channel_id')
        self.backup_channel_id = data.get('backup_channel_id')
        self.dry_run = DRY_RUN
        self.auto_confirm = AUTO_CONFIRM
        self.use_api_fallback = USE_API_FALLBACK
        self.download_delay = DOWNLOAD_DELAY_SECONDS
        self.initial_full_backup = INITIAL_FULL_BACKUP
        self.delete_after_upload = DELETE_AFTER_UPLOAD
        self.require_native_quality = REQUIRE_NATIVE_QUALITY
        self.upload_chunk_size_mb = UPLOAD_CHUNK_SIZE_MB
        self.video_privacy_status = VIDEO_PRIVACY_STATUS
        self.socket_timeout = SOCKET_TIMEOUT_SECONDS
        self.download_retries = DOWNLOAD_RETRIES
        self.fragment_retries = FRAGMENT_RETRIES
    
    @classmethod
    def load(cls):
        """Load configuration from file"""
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)
    
    def should_do_full_backup(self, state):
        """Determine if full backup should be performed"""
        return self.initial_full_backup and not state.get("full_backup_completed", False)
    
    def get_chunk_size_bytes(self):
        """Get upload chunk size in bytes (returns -1 for single chunk upload)"""
        if self.upload_chunk_size_mb <= 0:
            return -1
        return self.upload_chunk_size_mb * 1024 * 1024
    
    def get_privacy_status(self):
        """Get and validate privacy status for uploads"""
        valid_statuses = ['private', 'unlisted', 'public']
        status = self.video_privacy_status.lower()
        
        if status not in valid_statuses:
            print(f"⚠️  Invalid privacy status '{status}', using 'unlisted' as default")
            return 'unlisted'
        
        return status

# Setup wizard

def create_default_config():
    """Create default config.json file"""
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


def prompt_for_channel_ids():
    """Prompt user for channel IDs"""
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
    
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
        print(f"✓ Created configuration directory: {CONFIG_DIR}\n")
    
    if not check_client_secret():
        print(f"⚠️  Missing {CLIENT_SECRET_FILE}!\n")
        print(f"┌────────────────────────────────────────────────────┐")
        print(f"│ STEP-BY-STEP: Get OAuth 2.0 Credentials            │")
        print(f"└────────────────────────────────────────────────────┘\n")
        
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
        print(f"   → Move it to: {CONFIG_DIR}\n")
        
        print(f"┌────────────────────────────────────────────────────┐")
        print(f"│ After completing these steps, run the script again.│")
        print(f"└────────────────────────────────────────────────────┘")
        return False
    
    print("✓ Client secret file found\n")
    
    if not check_api_key():
        print(f"⚠️  Missing {API_KEY_FILE}!\n")
        print(f"┌────────────────────────────────────────────────────┐")
        print(f"│ STEP-BY-STEP: Get YouTube API Key                  │")
        print(f"└────────────────────────────────────────────────────┘\n")
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
        print(f"   → Save it in: {CONFIG_DIR}")
        print(f"   → ⚠️  IMPORTANT: Do NOT commit this file to repositories!\n")
        
        print(f"┌────────────────────────────────────────────────────┐")
        print(f"│ After creating api_key.txt, run the script again.  │")
        print(f"└────────────────────────────────────────────────────┘")
        return False
    
    print("✓ API key file found\n")
    
    if not os.path.exists(CONFIG_FILE):
        print(f"Creating {CONFIG_FILE}...\n")
        config = create_default_config()
    else:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    
    # Check and prompt for missing channel IDs
    config_updated = False
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
    
    if config_updated:
        with open(CONFIG_FILE, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=2)
        print(f"✓ Configuration saved to {CONFIG_FILE}\n")
    
    # Verify test user setup (only if token doesn't exist)
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
    
    chunk_display = f"{UPLOAD_CHUNK_SIZE_MB}MB" if UPLOAD_CHUNK_SIZE_MB > 0 else "Single chunk (entire file)"
    privacy_display_map = {
        'private': 'Private (only you can see)',
        'unlisted': 'Unlisted (accessible via link)',
        'public': 'Public (visible to everyone)'
    }
    privacy_display = privacy_display_map.get(VIDEO_PRIVACY_STATUS.lower(), VIDEO_PRIVACY_STATUS)
    
    print(f"\nBackup settings:")
    print(f"  • Configuration directory: {CONFIG_DIR}")
    print(f"  • Source Channel: {config['source_channel_id']}")
    print(f"  • Backup Channel: {config['backup_channel_id']}")
    print(f"  • Dry run mode: {'ENABLED (no uploads)' if DRY_RUN else 'Disabled'}")
    print(f"  • Auto confirm: {'ENABLED (no prompts)' if AUTO_CONFIRM else 'Disabled'}")
    print(f"  • Download method: yt-dlp + {'API fallback' if USE_API_FALLBACK else 'no fallback'}")
    print(f"  • Download delay: {DOWNLOAD_DELAY_SECONDS} seconds between videos")
    print(f"  • Backup mode: {'Full backup (API)' if INITIAL_FULL_BACKUP else 'Incremental (RSS)'}")
    print(f"  • Delete after upload: {'YES (files will be deleted)' if DELETE_AFTER_UPLOAD else 'NO (files kept in downloads/)'}")
    print(f"  • Require native quality: {'YES (abort if < 720p)' if REQUIRE_NATIVE_QUALITY else 'NO (accept any quality)'}")
    print(f"  • Upload chunk size: {chunk_display}")
    print(f"  • Video privacy: {privacy_display}")
    print(f"  • Archive file: {os.path.basename(ARCHIVE_FILE)}")
    print(f"  • Log file: {os.path.basename(LOG_FILE)}")
    print(f"  • Download directory: {DOWNLOAD_DIR}")
    print(f"\nAuthentication:")
    print(f"  • OAuth (for backup channel): {os.path.basename(CLIENT_SECRET_FILE)}")
    print(f"  • API Key (for source channel): {os.path.basename(API_KEY_FILE)}")
    
    print("\nSetup complete! Starting authentication...\n")
    return True