# YouTube Unlisted Finder

**Purpose:** `youtube_unlisted_finder` is a tool that scans your YouTube playlists (Watch Later included), or only the playlists and liked videos you choose, and writes a report of the unlisted videos it finds, using the YouTube Data API v3 for listing and classification and yt-dlp to read Watch Later.

## How it Works

- Authenticates with OAuth 2.0 using the read-only `youtube.readonly` scope; credentials and token live in the git-ignored `config/` folder.
- By default collects the video ids of all your own playlists through the Data API, plus Watch Later through yt-dlp with browser cookies (the API cannot read Watch Later).
- With `--playlist` and/or `--liked` scans only those sources instead.
- Removes duplicate ids, remembering every playlist each video was found in.
- Classifies the videos in batches of 50 with `videos.list` and keeps those whose privacy status is unlisted; videos the API does not return (private or deleted) are counted as skipped.
- Writes a Markdown, CSV or JSON report and prints a summary with the number of sources scanned, videos checked, unlisted found, videos skipped and API quota units used.
- If Watch Later cannot be read, logs a warning with a hint and continues with the rest of the scan.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

On the first run the tool prints a step-by-step guide to create a Google Cloud OAuth client (Desktop app): create the project, enable the YouTube Data API v3, configure the consent screen and add your Google account under Test users, then save the downloaded JSON as `config/client_secret.json` and run the tool again. An existing `client_secret.json` from another tool can be reused if your account is a test user of its project.

Reading Watch Later needs cookies from a logged-in browser. On Windows, Chrome must be closed during the run, and recent Chrome versions may refuse cookie extraction: in that case use `--browser firefox`, or export a `cookies.txt` and pass it with `--cookies-file`.

## Usage

All commands run from PowerShell inside the tool's virtual environment.

Scan all your playlists and Watch Later, writing a Markdown report in `reports/`:

```
.venv\Scripts\Activate.ps1; python main.py
```

Scan a single playlist (ID or URL) and write a CSV report:

```
.venv\Scripts\Activate.ps1; python main.py --playlist PLxxxxxxxxxxxx --format csv
```

Scan only the liked videos and save the report to a chosen path:

```
.venv\Scripts\Activate.ps1; python main.py --liked --output liked_unlisted.md
```

Scan everything except Watch Later:

```
.venv\Scripts\Activate.ps1; python main.py --no-watch-later
```

### Options

- `--playlist` / `-p` - Scan only this playlist, given as ID or URL; repeatable, and `WL` means Watch Later
- `--liked` / `-l` - Scan the liked videos; can be combined with `--playlist`
- `--no-watch-later` - Skip Watch Later in the default scan
- `--format` / `-f` - Report format: `md`, `csv` or `json` (default set by `DEFAULT_FORMAT` in `config.py`)
- `--output` / `-o` - Report path (default `reports/unlisted_<date>_<time>.<format>`)
- `--browser` - Browser whose cookies yt-dlp uses for Watch Later (default set by `COOKIES_FROM_BROWSER`)
- `--cookies-file` - Exported cookies.txt for Watch Later; overrides `--browser`

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```
