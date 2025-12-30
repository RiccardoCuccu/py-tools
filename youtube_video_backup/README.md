# YouTube Video Backup

**Purpose:** `youtube_video_backup.py` is a script designed to automatically backup videos from a YouTube channel to a secondary channel in private mode. The script can perform a full channel backup via API or monitor for new videos via RSS feed. It downloads videos with all metadata (title, description, tags, thumbnails) at their native resolution, and re-uploads them to a backup channel with identical settings. It uses yt-dlp for downloads and YouTube Data API v3 with OAuth 2.0 authentication for uploads.

## How it Works

- On first run, performs a complete backup of ALL videos from the source channel via YouTube Data API.
- Subsequent runs use RSS feed to check for new videos (no API quota required).
- Downloads videos with all original metadata at native quality (720p+).
- Re-uploads to backup channel as private videos with identical metadata.
- Checks for duplicates against both local archive and existing backup channel videos.
- Can resume interrupted backups from a persistent queue without re-fetching video lists.
- Tracks API quota usage and provides detailed progress reporting.

## Usage
```
python main.py
```

On the first run, the script will guide you through initial setup, asking for source and destination channel IDs.

## Installation

To use `youtube_video_backup.py`, you'll need to install the following Python libraries:

```
pip install yt-dlp google-api-python-client google-auth-oauthlib google-auth feedparser requests
```