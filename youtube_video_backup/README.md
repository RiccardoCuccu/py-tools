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
# Basic run - interactive prompts for each decision
python main.py

# Fully automated run - no prompts, use cached data, ignore quota warnings
python main.py --auto-confirm --use-cache --ignore-quota-warning

# Automated run that forces a fresh channel fetch
python main.py --auto-confirm --re-fetch --ignore-quota-warning

# Skip per-video confirmation only, still ask about cache and quota
python main.py --auto-confirm
```

On the first run, the script will guide you through initial setup, asking for source and destination channel IDs.

### Options

- `-y`, `--auto-confirm` - Skip the per-video backup confirmation prompt and always proceed
- `--use-cache` - Use cached channel data when available (no API cost); mutually exclusive with `--re-fetch`
- `--re-fetch` - Ignore cached channel data and re-fetch the full video list from the channel; mutually exclusive with `--use-cache`
- `--ignore-quota-warning` - Automatically continue when daily API quota may be insufficient, skipping the confirmation prompt

## Installation

To use `youtube_video_backup.py`, you'll need to install the following Python libraries:

```
pip install yt-dlp google-api-python-client google-auth-oauthlib google-auth feedparser requests Pillow pytz
```

Additionally, `ffmpeg` must be installed on your system and accessible via the command line. Follow the [official FFmpeg installation guide](https://ffmpeg.org/download.html) for your operating system.