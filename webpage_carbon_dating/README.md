# Webpage Carbon Dating

**Purpose:** `webpage_carbon_dating.py` is a script designed to retrieve the oldest recorded publication date of a webpage. This script uses `requests` to fetch the HTML of a given webpage and `BeautifulSoup` to parse it and search for metadata tags that usually contain the publication date (e.g., `article:published_time`, `datePublished`, etc.). If found, it returns the date of publication.

## How it Works

- The script sends an HTTP request to retrieve the HTML of the webpage.
- It then parses the HTML content to search for specific meta tags or `<time>` elements that typically store publication dates.
- Once found, it extracts and returns the date in the `YYYY-MM-DD` format.
- If no publication date is found, it returns a message indicating that the metadata is not available.

## Usage
```
python webpage_carbon_dating.py
```

Provide the webpage URL when prompted.

## Installation

To use `webpage_carbon_dating.py`, you'll need to install the following Python libraries:

```
pip install requests beautifulsoup4
```