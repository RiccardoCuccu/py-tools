# YouTube Video Backup

**Purpose:** `youtube_video_backup.py` is a script designed to automatically backup videos from a YouTube channel to a secondary channel in private mode. The script can perform a full channel backup via API or monitor for new videos via RSS feed. It downloads videos with all metadata (title, description, tags, thumbnails) at their native resolution, and re-uploads them to a backup channel with identical settings. It uses yt-dlp for downloads and YouTube Data API v3 with OAuth 2.0 authentication for uploads.

## How it Works

- The script uses OAuth 2.0 for uploading to the backup channel and an API key for reading public data from the source channel.
- On first run, it performs a full backup retrieving ALL videos from the source channel via YouTube Data API.
- Subsequent runs use RSS feed to check for new videos (~15 most recent, no API quota required).
- It checks both a local archive file and the backup channel's existing videos to avoid duplicates.
- For each new video, the script prompts for user confirmation before proceeding (unless AUTO_CONFIRM is enabled).
- The video is downloaded with all metadata (title, description, tags, category) and thumbnail.
- The video is then uploaded to the backup channel with all original metadata preserved and set as private.
- After successful upload, the video ID is saved to the local archive and temporary files are cleaned up.
- Progress and quota usage are tracked throughout the process.

## Usage
```
python youtube_video_backup.py
```

On the first run, the script will guide you through initial setup, asking for source and destination channel IDs.

## Installation

To use `youtube_video_backup.py`, you'll need to install the following Python libraries:

```
pip install yt-dlp google-api-python-client google-auth-oauthlib google-auth feedparser requests
```