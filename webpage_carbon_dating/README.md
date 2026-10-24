# Webpage Carbon Dating

**Purpose:** `webpage_carbon_dating.py` is a script designed to retrieve the oldest recorded publication date of a webpage. This script uses `requests` to fetch the HTML of a given webpage and `BeautifulSoup` to parse it and search for metadata tags that usually contain the publication date (e.g., `article:published_time`, `datePublished`, etc.). If found, it returns the date of publication.

## How it Works

- The script sends an HTTP request to retrieve the HTML of the webpage.
- It then parses the HTML content to search for specific meta tags or `<time>` elements that typically store publication dates.
- Once found, it extracts and returns the date in the `YYYY-MM-DD` format.
- If no publication date is found, it returns a message indicating that the metadata is not available.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

## Usage

Run the tool from PowerShell inside its virtual environment:

```
.venv\Scripts\Activate.ps1; python webpage_carbon_dating.py
```

Provide the webpage URL when prompted. A URL without a scheme is treated as `https`; network errors are reported as a message instead of a traceback.

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```