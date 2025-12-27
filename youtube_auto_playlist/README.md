# YouTube Subscription Auto Playlist

**Purpose:** `youtube_auto_playlist.py` is a script designed to automatically monitor all your YouTube subscriptions and add newly published videos to a predefined playlist. The script uses the YouTube Data API v3 with OAuth 2.0 authentication to securely access your account and manage playlists. It keeps track of already processed videos locally to avoid duplicates.

## How it Works

- The script authenticates the user via OAuth 2.0 using the YouTube Data API.
- It retrieves all channels from your subscriptions list.
- It checks for new videos published since the last check using RSS feeds (no API quota) or API search.
- Any new video found is automatically added to your target playlist.
- The script logs all added videos with timestamps, titles, and links.
- It updates a local state file to ensure the same video is never added twice.

## Usage
```
python youtube_auto_playlist.py

```

On the first run, the script will guide you through initial setup.

## Installation

To use `youtube_auto_playlist.py`, you'll need to install the following Python libraries:

```
pip install google-api-python-client google-auth google-auth-oauthlib pyyaml

```