# YouTube Subscription Auto Playlist

**Purpose:** `youtube_auto_playlist.py` is a script designed to automatically monitor all your YouTube subscriptions and add newly published videos to a predefined playlist. The script uses the YouTube Data API v3 with OAuth 2.0 authentication to securely access your account and manage playlists. It keeps track of already processed videos locally to avoid duplicates.

## How it Works

- The script authenticates the user via OAuth 2.0 using the YouTube Data API.
- It retrieves all channels from your subscriptions list (alphabetically sorted).
- It checks for new videos published since the last check using RSS feeds (no API quota) or API search.
- Any new video found is automatically added to your target playlist or simulated in dry-run mode.
- The script logs all added videos with timestamps, titles, and links.
- It updates a local state file to ensure the same video is never added twice and tracks daily quota usage.
- The check window only advances when every channel was fetched and every video was added; otherwise the same window is retried on the next cycle.
- Dry-run mode (`DRY_RUN = True`) writes nothing except the quota counter: no log entries, no processed ids and no window advance, so disabling it later adds those videos.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

## Usage

Run the tool from PowerShell inside its virtual environment:

```
.venv\Scripts\Activate.ps1; python youtube_auto_playlist.py
```

On the first run, the script will guide you through initial setup. The playlist ID can be pasted either as the bare ID or as a playlist URL containing `list=`.

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```
