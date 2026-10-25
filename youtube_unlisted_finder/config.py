#!/usr/bin/env python3
"""
Configuration constants and first-run setup for YouTube Unlisted Finder.
"""

import os

# ---------------------------------------------------------------------------
# GENERAL CONFIGURATION - EDIT THESE VALUES
# ---------------------------------------------------------------------------

# Report format used when --format is not given: "md", "csv" or "json"
DEFAULT_FORMAT = "md"

# Browser whose cookies yt-dlp reads to list Watch Later (Watch Later is not
# exposed by the Data API). Leave empty to disable. Chrome must be closed on
# Windows, otherwise its cookie database is locked.
COOKIES_FROM_BROWSER = "chrome"

# Netscape-format cookies.txt exported from a browser; takes precedence over
# COOKIES_FROM_BROWSER when set
COOKIES_FILE = ""

# Include Watch Later in the default scan (overridden by --no-watch-later)
INCLUDE_WATCH_LATER = True

# Folder (inside the tool folder) where reports are written by default
REPORTS_DIR_NAME = "reports"

# ---------------------------------------------------------------------------
# TECHNICAL CONFIGURATION (DO NOT EDIT)
# ---------------------------------------------------------------------------

# OAuth scope: read-only access is enough to list playlists and classify videos
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Generated and secret files live in CONFIG_DIR (not in the repository)
CONFIG_DIR = os.path.join(SCRIPT_DIR, "config")
CLIENT_SECRET_FILE = os.path.join(CONFIG_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")
LOG_FILE = os.path.join(CONFIG_DIR, "log.txt")
REPORTS_DIR = os.path.join(SCRIPT_DIR, REPORTS_DIR_NAME)

# Accepted values
VALID_FORMATS = ("md", "csv", "json")
SUPPORTED_BROWSERS = (
    "brave", "chrome", "chromium", "edge", "firefox", "opera", "safari",
    "vivaldi", "whale",
)

# YouTube Data API
VIDEOS_LIST_BATCH_SIZE = 50
API_PAGE_SIZE = 50
QUOTA_LIST_CALL_COST = 1  # every list call used here costs one unit

# Pseudo playlist ids and titles
WATCH_LATER_ID = "WL"
WATCH_LATER_TITLE = "Watch Later"
LIKED_TITLE = "Liked videos"

CLIENT_SECRET_HELP = """Missing {client_secret_path}

This tool needs an OAuth client to read your YouTube account (read-only).
The client belongs to a Google Cloud project, not to a channel: you choose
the channel when you log in. You can reuse the client_secret.json of another
tool (e.g. youtube_video_backup) as long as the Google account you log in with
is listed under 'Test users' of that project (see STEP 3).

To create a new one:

  STEP 1 - Project
    Open https://console.cloud.google.com/projectcreate, name the project
    (e.g. "youtube-unlisted-finder") and click Create. Check that it is the
    selected project in the picker at the top of the page.

  STEP 2 - Enable the API
    Open https://console.cloud.google.com/apis/library/youtube.googleapis.com
    and click Enable.

  STEP 3 - Consent screen and test user
    Open https://console.cloud.google.com/auth/overview and click 'Get started':
      - App information: any app name (e.g. "Unlisted Finder"), your email as
        user support email, then Next.
      - Audience: choose 'External', then Next.
      - Contact information: your email, then Next.
      - Accept the policy, then Create.
    Open https://console.cloud.google.com/auth/audience, under 'Test users'
    click '+ Add users', enter the email of the Google account you will log in
    with (for a Brand Account channel: the personal account that manages it)
    and click Save. Leave the publishing status on 'Testing': no Google
    verification is needed.

  STEP 4 - OAuth client
    Open https://console.cloud.google.com/auth/clients, click '+ Create client',
    choose Application type 'Desktop app', any name, then Create.
    In the dialog that appears click 'Download JSON'.

  STEP 5 - Install the file
    Rename the downloaded file to client_secret.json and move it to:
      {config_dir}
    Run the tool again: a browser opens. Log in with the test user account,
    pick the channel if asked, and on the 'Google hasn't verified this app'
    warning click Continue.

Note: while the project is in 'Testing', Google expires the login after
7 days; the tool then simply opens the browser again to log in.
"""


def first_run_setup() -> bool:
    """
    Create the config folder and check that Google credentials are present.

    Prints the setup guide and returns False when client_secret.json is
    missing, True when the tool is ready to authenticate.
    """
    if not os.path.isdir(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
        print(f"Created configuration directory: {CONFIG_DIR}\n")

    if os.path.exists(CLIENT_SECRET_FILE):
        return True

    print(CLIENT_SECRET_HELP.format(
        client_secret_path=CLIENT_SECRET_FILE, config_dir=CONFIG_DIR
    ))
    return False
