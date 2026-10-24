# YouTube Video Backup

**Purpose:** `youtube_video_backup.py` is a script designed to automatically backup videos from a YouTube channel to a secondary channel in private mode. The script can perform a full channel backup via API or monitor for new videos via RSS feed. It downloads videos with all metadata (title, description, tags, thumbnails) at their native resolution, and re-uploads them to a backup channel with identical settings. It uses yt-dlp for downloads and YouTube Data API v3 with OAuth 2.0 authentication for uploads.

## How it Works

- On first run, performs a complete backup of ALL videos from the source channel via YouTube Data API.
- Subsequent runs use RSS feed to check for new videos (no API quota required).
- After OAuth authentication and before any download or upload (dry runs included), checks that the authenticated channel matches `backup_channel_id` in `config.json` and aborts otherwise (1 quota unit).
- Downloads videos with all original metadata at native quality (1080p+ by default, set by `MIN_NATIVE_HEIGHT` in `config.py`).
- Re-uploads to backup channel as private videos with identical metadata.
- Skips videos already listed in the local archive (`config/archive.txt`); a dry run never writes to it.
- Can resume an interrupted full backup from the cached channel list without re-fetching it; incremental runs always read the RSS feed and merge it into the cache, so new videos are found even with `--auto-confirm`.
- Stops the run when YouTube reports the daily upload limit or the API quota as exhausted.
- Tracks API quota usage and provides detailed progress reporting.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

Additionally, `ffmpeg` must be installed on your system and accessible via the command line. Follow the [official FFmpeg installation guide](https://ffmpeg.org/download.html) for your operating system.

## Usage

All commands run from PowerShell inside the tool's virtual environment.

Basic run, with interactive prompts for each decision:

```
.venv\Scripts\Activate.ps1; python main.py
```

Fully automated run (no prompts, use cached data, ignore quota warnings):

```
.venv\Scripts\Activate.ps1; python main.py --auto-confirm --use-cache --ignore-quota-warning
```

Automated run that forces a fresh channel fetch:

```
.venv\Scripts\Activate.ps1; python main.py --auto-confirm --re-fetch --ignore-quota-warning
```

Skip the per-video confirmation only, still asking about cache and quota:

```
.venv\Scripts\Activate.ps1; python main.py --auto-confirm
```

On the first run, the script will guide you through initial setup, asking for source and destination channel IDs.

### Options

- `-y`, `--auto-confirm` - Skip the per-video backup confirmation prompt and always proceed
- `--use-cache` - Use cached channel data when resuming an unfinished full backup (no API cost); mutually exclusive with `--re-fetch`
- `--re-fetch` - Ignore cached channel data and re-fetch the full video list from the channel; mutually exclusive with `--use-cache`
- `--ignore-quota-warning` - Automatically continue when daily API quota may be insufficient, skipping the confirmation prompt

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```
