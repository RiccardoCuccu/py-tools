# Google Podcasts URL Decoder

**Purpose:** `google_podcast_decoder.py` is a script designed to decode Google Podcasts URLs to extract podcast episode information from RSS feeds. It supports both interactive mode and command-line arguments, allowing users to retrieve show and episode details from encoded Google Podcasts links.

## How it Works

- The script extracts Base64-encoded feed URL and episode ID from a Google Podcasts URL using regex pattern matching.
- It decodes both the RSS feed URL and the episode ID from their Base64-encoded format (standard or URL-safe alphabet, padding optional) and accepts only http(s) feed URLs.
- The script fetches the RSS feed content from the podcast host using the decoded feed URL.
- It parses the XML content to search for the specific episode matching the decoded episode ID, preferring an exact GUID match.
- Once found, it extracts and displays comprehensive information including show details (title, description), episode details (title, publication date, description, audio URL), and direct links.
- The script can be used either by providing the URL as a command-line argument or through an interactive prompt mode, and exits with code 1 when decoding, fetching or the episode lookup fails.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

## Usage

Run the tool from PowerShell inside its virtual environment:

```
.venv\Scripts\Activate.ps1; python google_podcast_decoder.py "GOOGLE_PODCASTS_URL"
```

Or run without arguments for interactive mode.

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```