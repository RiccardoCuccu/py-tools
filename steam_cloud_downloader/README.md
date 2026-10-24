# Steam Cloud Downloader

**Purpose:** `steam_cloud_downloader.py` is a script designed to automate the process of downloading game save files stored in Steam Cloud for all games linked to a Steam account. The tool also organizes the downloaded files into folders named after the respective games in snake_case format and archives the data for backup purposes.

## How it Works

- The script begins by automating the Steam login process using Selenium. A browser window opens, allowing the user to manually log in to their Steam account, including completing any required two-factor authentication.
- After a successful login, the script retrieves session cookies to authenticate subsequent HTTP requests made with the `requests` library.
- It navigates to the Steam Remote Storage page and scrapes the list of all app IDs (corresponding to games) linked to the account.
- For each app ID, the script fetches the respective game name, converts it into snake_case format, and creates a folder for the game's save files.
- It downloads all available files for each game into the corresponding folder, skipping games if their folders already contain files. File names are sanitized so nothing can be written outside the game folder, and a game with any failed download is discarded so the next run retries it.
- Once all downloads are complete, the script creates a ZIP archive of all downloaded files and, only after the archive is confirmed on disk, cleans up the original folders to save space.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

Additionally, you must have a recent version of Google Chrome installed for Selenium automation.

## Usage

Run the tool from PowerShell inside its virtual environment:

```
.venv\Scripts\Activate.ps1; python steam_cloud_downloader.py
```

Log in to Steam when the browser window opens.

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```