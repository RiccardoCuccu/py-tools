# Social Media Tracker

**Purpose:** `social_media_tracker` is a tool that automatically tracks follower counts across Instagram, Threads, and YouTube on a configurable schedule, appending results to an Excel file with historical tracking and change calculations.

## How it Works

- The tool loads platform URLs and schedule settings from `social_profiles.json`.
- It runs continuously in the background, checking the schedule every minute.
- When the scheduled time arrives (daily, weekly, or monthly), it collects follower counts from all enabled platforms.
- Instagram is scraped via headless Chrome (Selenium) using the public `span[title]` element - no login required.
- Threads is scraped via HTTP requests by parsing embedded JSON in the profile page.
- YouTube subscriber counts are fetched via yt-dlp without requiring an API key.
- Each platform's data is saved to its own worksheet in an Excel file with date, time, username, follower count, and change from the previous check.
- Color-coded change indicators (green for growth, red for decline) make trends easy to spot.
- All platforms include retry logic to handle transient failures and rate limiting.

## Usage

```
python main.py
```

On the first run, a default `social_profiles.json` is created. Edit it to add your profile URLs and enable the platforms you want to track.

## Installation

```
pip install requests schedule openpyxl selenium webdriver-manager yt-dlp
```

A virtual environment is recommended:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

Chrome must be installed on the system for Instagram scraping (Selenium uses it in headless mode). `webdriver-manager` downloads the matching ChromeDriver automatically.
