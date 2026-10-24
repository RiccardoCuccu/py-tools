# Social Media Tracker

**Purpose:** `social_media_tracker` is a tool that automatically tracks follower counts across Instagram, Threads, and YouTube on a configurable schedule, appending results to an Excel file with historical tracking and change calculations.

## How it Works

- The tool loads platform URLs and schedule settings from `social_profiles.json`.
- It runs continuously in the background, checking the schedule every minute.
- When the scheduled time arrives (daily, weekly, or monthly), it collects follower counts from all enabled platforms.
- Instagram is read without login: first the public web profile API, then the profile page HTML, and finally headless Chrome (Selenium) via the `span[title]` element as a last resort.
- Threads is scraped via HTTP requests by parsing embedded JSON in the profile page.
- YouTube subscriber counts are fetched via yt-dlp without requiring an API key.
- Each platform's data is saved to its own worksheet in an Excel file with date, time, username, follower count, and change from the previous check.
- Color-coded change indicators (green for growth, red for decline) make trends easy to spot.
- All platforms include retry logic to handle transient failures and rate limiting.
- The config is validated on every load (schedule mode, `HH:MM` time, weekday), and a failed run (for example the Excel file being open) is reported without stopping the scheduler.
- At most one row is recorded per platform per period (day, ISO week or month), so a startup check and the scheduled run in the same period never duplicate a row; platforms already recorded are not scraped again, and an `Error` row is replaced by a later successful run in the same period.
- The Excel file is saved through a temporary file so an interrupted write cannot corrupt the history.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

Chrome must be installed on the system for Instagram scraping (Selenium uses it in headless mode). `webdriver-manager` downloads the matching ChromeDriver automatically.

## Usage

Run the tool from PowerShell inside its virtual environment:

```
.venv\Scripts\Activate.ps1; python main.py
```

On the first run, a default `social_profiles.json` is created. Edit it to add your profile URLs and enable the platforms you want to track.

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```
