"""Configuration file - all configurable parameters for Amazon Product Price Scraper"""

import logging
import json
from pathlib import Path

# ============================================================================
# FETCHER CONFIGURATION
# ============================================================================

# Enable/disable individual fetching mechanisms
# Set to True to enable, False to disable
ENABLE_FETCHER_API = True      # Amazon Product Advertising API (PA-API)
ENABLE_FETCHER_HTML = True     # HTML scraping with BeautifulSoup
ENABLE_FETCHER_BROWSER = True  # Browser automation with Playwright

# Fetcher execution order
# The scraper will try each method in this order until one succeeds
# Valid values: 'api', 'html', 'browser'
# Only enabled fetchers will be used
FETCHER_ORDER = ['api', 'html', 'browser']

# ============================================================================
# PA-API FETCHER CONFIGURATION (fetcher_api.py)
# ============================================================================

# Amazon Product Advertising API settings
# Credentials (access_key, secret_key) are loaded from config.json

# Target Amazon marketplace
# Supported: IT, US, UK, DE, FR, ES, CA, JP, IN, AU, BR, MX, NL, PL, SE, SG, TR, AE, SA, EG
# This determines which Amazon store to query and affects price currency
TARGET_MARKETPLACE = "IT"

# PA-API request throttling (requests per second)
# Amazon enforces rate limits - do not increase above 1.0
PA_API_THROTTLING = 1.0

# Enable batch API requests (up to 10 ASINs per request)
# Significantly improves performance for large product lists
ENABLE_API_BATCH_REQUESTS = True

# Batch size for API requests (max 10 per Amazon PA-API limit)
API_BATCH_SIZE = 5

# ============================================================================
# HTML SCRAPER FETCHER CONFIGURATION (fetcher_html.py)
# ============================================================================

# User-Agent rotation pool for HTML requests
# The scraper randomly selects one User-Agent per request to reduce blocking
# Update these periodically to match current browser versions
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

# HTTP connection pool settings
# Maximum number of concurrent connections
HTML_CONNECTION_POOL_LIMIT = 10

# Maximum connections per host
HTML_CONNECTION_POOL_LIMIT_PER_HOST = 5

# ============================================================================
# BROWSER FETCHER CONFIGURATION (fetcher_browser.py)
# ============================================================================

# Browser type for Playwright
# Options: 'chromium', 'firefox', 'webkit'
# Chromium is recommended for best compatibility with Amazon
BROWSER_TYPE = 'chromium'

# Run browser in headless mode (no visible window)
# Set to False for debugging to see the browser in action
BROWSER_HEADLESS = True

# Browser page load timeout (in milliseconds)
# Increase if pages take longer to load in your region
BROWSER_PAGE_TIMEOUT = 15000

# Browser viewport size (width x height in pixels)
# Simulates a desktop screen resolution
BROWSER_VIEWPORT_WIDTH = 1920
BROWSER_VIEWPORT_HEIGHT = 1080

# Browser locale settings
# Used to match your target marketplace language
BROWSER_LOCALE = 'it-IT'

# Browser timezone
# Used for accurate time-based content rendering
BROWSER_TIMEZONE = 'Europe/Rome'

# Postal code for Amazon delivery address
# Amazon shows different prices/availability based on delivery location
# Format varies by country:
#   - Italy: 5-digit (e.g., "00100" for Rome)
#   - Germany: 5-digit (e.g., "10115" for Berlin)
#   - US: 5-digit ZIP (e.g., "10001" for New York)
#   - UK: Postcode (e.g., "SW1A 1AA" for London)
# Set to None to skip automatic address configuration
BROWSER_DELIVERY_POSTAL_CODE = "00100"

# ============================================================================
# IMAGE DOWNLOAD CONFIGURATION
# ============================================================================

# Enable/disable product image downloads
# When True, images are saved to IMAGES_OUTPUT_DIR with ASIN-based naming
ENABLE_IMAGE_DOWNLOAD = True

# Directory where product images will be saved
# Images are named as: {ASIN}.jpg
IMAGES_OUTPUT_DIR = "images"

# Maximum retry attempts for failed image downloads
# Exponential backoff: 1s, 2s, 4s, etc.
IMAGE_DOWNLOAD_MAX_RETRIES = 3

# ============================================================================
# REQUEST CONFIGURATION
# ============================================================================

# Delay between processing URLs (in seconds)
# Helps avoid rate limiting and reduces server load
# Set to 0 to disable delay
REQUEST_DELAY = 2.0

# HTTP request timeout (in seconds)
# Used for all web requests (HTML scraping, image downloads)
REQUEST_TIMEOUT = 15

# Maximum retry attempts for failed HTTP requests
# Applies to HTML scraping and API calls
MAX_HTTP_RETRIES = 3

# Retry delay range (min, max) in seconds
# Random delay between retries to avoid detection patterns
RETRY_DELAY_MIN = 2.0
RETRY_DELAY_MAX = 5.0

# ============================================================================
# PRICE VALIDATION CONFIGURATION
# ============================================================================

# Valid price range (min and max acceptable prices in local currency)
# Prices outside this range are considered parsing errors and rejected
MIN_VALID_PRICE = 0.01
MAX_VALID_PRICE = 999999.99

# ============================================================================
# URL PROCESSING CONFIGURATION
# ============================================================================

# Amazon short URL domains that require expansion
# The scraper automatically follows redirects for these domains
SHORT_URL_DOMAINS = ['amzn.eu', 'amzn.to', 'amzn.com', 'a.co']

# Timeout for expanding short URLs (in seconds)
SHORT_URL_EXPANSION_TIMEOUT = 10

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

# Logging level for console and file output
# Options: logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR
LOG_LEVEL = logging.INFO

# Log file path
# All operations are logged here with timestamps
LOG_FILE = "scraper.log"

# ============================================================================
# OUTPUT CONFIGURATION
# ============================================================================

# Price format in output file
# Options: 'symbol' (€29.99), 'code' (EUR 29.99), 'number' (29.99)
PRICE_FORMAT = 'symbol'

# Currency symbol for price formatting (used when PRICE_FORMAT='symbol')
# Auto-detected based on TARGET_MARKETPLACE if left as None
CURRENCY_SYMBOL = None

# ============================================================================
# MARKETPLACE CONFIGURATION (AUTO-DETECTED)
# ============================================================================

# Currency symbols by marketplace (used for price formatting)
MARKETPLACE_CURRENCIES = {
    'IT': '€', 'DE': '€', 'FR': '€', 'ES': '€', 'NL': '€', 'PL': 'zł', 'SE': 'kr',
    'US': '$', 'CA': 'CA$', 'MX': 'MX$', 'BR': 'R$',
    'UK': '£',
    'JP': '¥', 'IN': '₹', 'AU': 'AU$', 'SG': 'S$', 'TR': '₺', 'AE': 'د.إ', 'SA': 'ر.س', 'EG': 'E£'
}

# Auto-detect currency symbol if not set
if CURRENCY_SYMBOL is None:
    CURRENCY_SYMBOL = MARKETPLACE_CURRENCIES.get(TARGET_MARKETPLACE, '€')

# ============================================================================
# PA-API CREDENTIALS (LOADED FROM config.json)
# ============================================================================

def load_api_credentials():
    """Load PA-API credentials from config.json file"""
    config_file = Path(__file__).parent / 'config.json'
    
    if not config_file.exists():
        return None
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            credentials = json.load(f)
        
        access_key = credentials.get('access_key')
        secret_key = credentials.get('secret_key')
        
        if not access_key or not secret_key or not isinstance(access_key, str) or not isinstance(secret_key, str):
            logging.warning("[Config] config.json exists but credentials are empty or invalid")
            return None
        
        return credentials
        
    except (json.JSONDecodeError, Exception) as e:
        logging.warning(f"[Config] Failed to load config.json: {e}")
        return None


# Load credentials on module import
_api_credentials = load_api_credentials()

# PA-API credentials (None if config.json not found or invalid)
PA_API_ACCESS_KEY = _api_credentials.get('access_key') if _api_credentials else None
PA_API_SECRET_KEY = _api_credentials.get('secret_key') if _api_credentials else None

# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================

def validate_configuration():
    """Validate all configuration settings and raise descriptive errors if invalid"""
    errors = []
    
    # Fetchers
    if not any([ENABLE_FETCHER_API, ENABLE_FETCHER_HTML, ENABLE_FETCHER_BROWSER]):
        errors.append("No fetchers enabled - at least one must be enabled")
    
    invalid_fetchers = set(FETCHER_ORDER) - {'api', 'html', 'browser'}
    if invalid_fetchers:
        errors.append(f"Invalid fetchers in FETCHER_ORDER: {invalid_fetchers}")
    
    enabled_map = {
        'api': ENABLE_FETCHER_API,
        'html': ENABLE_FETCHER_HTML,
        'browser': ENABLE_FETCHER_BROWSER
    }
    disabled_in_order = [f for f in FETCHER_ORDER if not enabled_map.get(f, False)]
    if disabled_in_order:
        errors.append(f"FETCHER_ORDER contains disabled fetchers: {disabled_in_order}")
    
    # Price range
    if MIN_VALID_PRICE >= MAX_VALID_PRICE:
        errors.append(f"MIN_VALID_PRICE ({MIN_VALID_PRICE}) must be < MAX_VALID_PRICE ({MAX_VALID_PRICE})")
    
    # Browser
    if ENABLE_FETCHER_BROWSER and BROWSER_TYPE not in {'chromium', 'firefox', 'webkit'}:
        errors.append(f"Invalid BROWSER_TYPE: '{BROWSER_TYPE}' - must be chromium, firefox, or webkit")
    
    # Request config
    if REQUEST_DELAY < 0:
        errors.append(f"REQUEST_DELAY must be >= 0, got {REQUEST_DELAY}")
    
    if RETRY_DELAY_MIN > RETRY_DELAY_MAX:
        errors.append(f"RETRY_DELAY_MIN ({RETRY_DELAY_MIN}) must be <= RETRY_DELAY_MAX ({RETRY_DELAY_MAX})")
    
    if errors:
        raise ValueError("Configuration errors:\n  - " + "\n  - ".join(errors))
    
    # Warnings
    if ENABLE_FETCHER_API and not (PA_API_ACCESS_KEY and PA_API_SECRET_KEY):
        logging.warning("[Config] PA-API enabled but credentials missing in config.json")
    
    return True


# Run validation on import
validate_configuration()