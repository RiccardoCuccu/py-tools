# Amazon Product Price Scraper

**Purpose:** `amazon_product_info` is a tool that extracts prices, names, and images from Amazon product URLs. It uses three independent fetching methods (PA-API, HTML scraping, browser automation) that can be enabled, disabled, and ordered according to your needs. All settings are centralized in a single configuration file.

## How it Works

- The script reads Amazon URLs from an input text file (one per line). Lines starting with `#` are treated as comments and ignored.
- It validates and sanitizes each URL, automatically expanding short URLs to full Amazon product links in the format `https://amazon.XX/dp/ASIN`.
- Based on the configured fetcher order, the script attempts to extract product data using up to three methods:
  - **PA-API (fetcher_api.py)**: Uses Amazon's official Product Advertising API for fastest and most reliable results. Requires API credentials in `config.json`.
  - **HTML Scraper (fetcher_html.py)**: Parses Amazon product pages using BeautifulSoup. Fast but may encounter CAPTCHA blocks.
  - **Browser Automation (fetcher_browser.py)**: Uses Playwright to render JavaScript content and bypass CAPTCHA. Slowest but most reliable for difficult cases.
- Each fetcher is tried in sequence until one successfully extracts the price and product name. If all fail, the product is marked as failed.
- Product images are optionally downloaded and saved with ASIN-based filenames (`{ASIN}.jpg`) to a configurable directory.
- Results are written to an output file showing cleaned URLs, prices (with currency symbols), and product names. Failed extractions are marked with `N/A` or `# FAILED`.
- At the end, a detailed summary displays overall statistics and performance metrics for each fetcher (attempts, successes, failures, success rate).

## Usage

```bash
python main.py input.txt output.txt
```

**Input file format:**
```
# This line is ignored
https://www.amazon.it/Logbook-PRO-Bodybuilding-Powerbuilding-Streetlifting/dp/B0CWX8H8WD/
https://www.amazon.it/gp/aw/d/B0FP2TZ49R/
https://www.amazon.de/dp/B0B31K85HC?th=1&psc=1
https://www.amazon.ie/gp/product/B0BW777FW2
https://amzn.eu/d/a2AbBH4
https://amzn.to/3Y03PIX
```

**config.json file format:**
```json
{
  "access_key": "YOUR_AMAZON_ACCESS_KEY_HERE",
  "secret_key": "YOUR_AMAZON_SECRET_KEY_HERE"
}
```

Get credentials at: https://affiliate-program.amazon.com/assoc_credentials/home

## Installation

To use `amazon_product_info`, you need to install the following Python libraries:

```bash
pip install aiohttp beautifulsoup4 lxml requests tqdm python-amazon-paapi playwright
playwright install chromium
```