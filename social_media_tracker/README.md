# Social Media Follower Tracker

**Purpose:** `social_media_tracker.py` is a tool designed to automatically track follower counts across Instagram, Threads and YouTube on a configurable schedule. The script runs continuously and checks follower numbers on the last day of each month (or daily/weekly) at a specified time, logging all data to an Excel file with historical tracking and change calculations.

## How it Works

- The script loads configuration from `social_profiles.json` with platform URLs and schedule settings.
- It runs continuously in the background, checking the schedule every minute.
- When the scheduled time arrives (daily, monthly or weekly), it collects follower counts from all enabled platforms.
- Follower data is scraped from public profile pages without requiring authentication.
- Each platform's data is saved to its own worksheet in an Excel file with date, time, username, followers, and change from previous check.
- The script includes retry logic to handle temporary failures and rate limiting.
- Color-coded change indicators (green for growth, red for decline) make trends easy to spot.

## Usage

```
python social_media_tracker.py
```

On the first run, the script will create a default `social_profiles.json` configuration file to update.

## Installation

To use `social_media_tracker.py`, you'll need to install the following Python libraries:

```
pip install requests schedule openpyxl instaloader yt-dlp
```

If you don't need Instagram tracking, you can skip installing `instaloader`. The script will automatically disable Instagram tracking and continue working for YouTube.