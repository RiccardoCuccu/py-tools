# Google Podcasts URL Decoder

**Purpose:** `google_podcasts_decoder.py` is a script designed to decode Google Podcasts URLs to extract podcast episode information from RSS feeds. It supports both interactive mode and command-line arguments, allowing users to retrieve show and episode details from encoded Google Podcasts links.

## How it Works

- The script extracts Base64-encoded feed URL and episode ID from a Google Podcasts URL using regex pattern matching.
- It decodes both the RSS feed URL and the episode ID from their Base64-encoded format.
- The script fetches the RSS feed content from the podcast host using the decoded feed URL.
- It parses the XML content to search for the specific episode matching the decoded episode ID.
- Once found, it extracts and displays comprehensive information including show details (title, description), episode details (title, publication date, description, audio URL), and direct links.
- The script can be used either by providing the URL as a command-line argument or through an interactive prompt mode.

## Usage
```
python google_podcasts_decoder.py "GOOGLE_PODCASTS_URL"
```

Or run without arguments for interactive mode.

## Installation

To use `google_podcasts_decoder.py`, you'll need to install the following Python library:

```
pip install requests
```