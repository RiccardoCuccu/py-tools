# Amazon Product Price Scraper

**Purpose:** `amazon_product_info` is a tool that extracts prices, names, and images from Amazon product URLs. It uses three independent fetching methods (PA-API, HTML scraping, browser automation) that can be enabled, disabled, and ordered according to your needs.

## How it Works

- The script reads Amazon URLs from an input text file (one per line). Lines starting with `#` are treated as comments and ignored.
- It validates and sanitizes each URL, automatically expanding short URLs to full Amazon product links in the format `https://amazon.XX/dp/ASIN`.
- Based on the configured fetcher order, the script attempts to extract product data using up to three methods:
  - **PA-API (fetcher_api.py)**: Uses Amazon's official Product Advertising API for fastest and most reliable results. Requires API credentials in `config.json`.
  - **HTML Scraper (fetcher_html.py)**: Parses Amazon product pages using BeautifulSoup. Fast but may encounter CAPTCHA blocks.
  - **Browser Automation (fetcher_browser.py)**: Uses Playwright to render JavaScript content and bypass CAPTCHA. Slowest but most reliable for difficult cases.
- Each fetcher is tried in sequence until one successfully extracts the price and product name. With batching enabled, PA-API handles URLs in batches and only URLs it cannot fully resolve fall back to the other fetchers. If all fail, the product is marked as failed.
- Product images are optionally downloaded and saved with ASIN-based filenames (`{ASIN}.jpg`) to a configurable directory.
- Results are written to an output file showing cleaned URLs, prices (with currency symbols), and product names. Failed extractions are marked with `N/A` or `# FAILED`.
- At the end, a detailed summary displays overall statistics and performance metrics for each fetcher (attempts, successes, failures, success rate).

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

After installing, run `playwright install chromium` to download the browser binary used by the browser fetcher.

## Usage

Run the tool from PowerShell inside its virtual environment:

```
.venv\Scripts\Activate.ps1; python main.py input.txt output.txt
```

The input file contains one Amazon URL per line. Lines starting with `#` are ignored. PA-API credentials for the optional API fetcher must be placed in a `config.json` file next to `main.py` with `access_key`, `secret_key` and `partner_tag` (your Associates tag, required by PA-API requests) fields. Get credentials at: https://affiliate-program.amazon.com/assoc_credentials/home

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```