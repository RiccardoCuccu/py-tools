#!/usr/bin/env python3
"""
Configuration for the Bitcoin Price Models tool: tunable values, paths and constants.
"""

import os

# ---------------------------------------------------------------------------
# GENERAL CONFIGURATION - EDIT THESE VALUES
# ---------------------------------------------------------------------------

# Startup behaviour: initial chart mode ("golden" or "powerlaw") and browser opening
DEFAULT_MODE = "golden"
OPEN_BROWSER = True

# Golden Ratio Multiplier: window of the moving average and band multipliers
MOVING_AVERAGE_DAYS = 350
GOLDEN_RATIO = 1.6
GOLDEN_RATIO_MULTIPLIERS = [GOLDEN_RATIO, 2, 3, 5]

# Power law projection: years drawn after the next halving, and the horizon
# in years from the last price when no next halving is known
PROJECTION_YEARS_AFTER_NEXT_HALVING = 4
PROJECTION_FALLBACK_YEARS = 6

# Rainbow bands as (name, colour), bottom to top
RAINBOW_BANDS = [
    ("Fire sale!", "#4472c4"),
    ("BUY!", "#54989f"),
    ("Accumulate", "#63be7b"),
    ("Still cheap", "#b1d580"),
    ("HODL!", "#feeb84"),
    ("Is this a bubble?", "#f6b45a"),
    ("FOMO Intensifies", "#ed7d31"),
    ("Sell. Seriously, SELL!", "#d64018"),
    ("Maximum bubble territory", "#c00200"),
]

# Line colours
PRICE_COLOR = "#2196F3"
MOVING_AVERAGE_COLOR = "#9E9E9E"
GOLDEN_BAND_COLOR = "#00A86B"
# One colour per non-golden multiplier, cool to warm as the multiple grows;
# green is reserved for the golden ratio band
BAND_COLORS = [
    "#FFB300",
    "#FB8C00",
    "#C62828",
]
# Power law fair value line
FAIR_VALUE_COLOR = "#212121"
if len(BAND_COLORS) != len(GOLDEN_RATIO_MULTIPLIERS) - 1:
    raise ValueError("BAND_COLORS needs one colour per non-golden multiplier")

# ---------------------------------------------------------------------------
# TECHNICAL CONFIGURATION (DO NOT EDIT)
# ---------------------------------------------------------------------------

# Script and data paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
CHART_FILE = os.path.join(OUTPUT_DIR, "chart.html")
TEMPLATES_DIR = os.path.join(SCRIPT_DIR, "templates")
CHART_TEMPLATE = os.path.join(TEMPLATES_DIR, "chart.html")
CHART_SCRIPT = os.path.join(TEMPLATES_DIR, "chart.js")
JSON_FILE = os.path.join(DATA_DIR, "market-price.json")
LOG_FILE = os.path.join(DATA_DIR, "log.txt")
TEMP_FILE_SUFFIX = ".tmp"
LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# Keys of the blockchain.com export
DATA_KEY = "market-price"
TIMESTAMP_KEY = "x"
PRICE_KEY = "y"

# Download settings and keys of the blockchain.com API response
DATA_URL = (
    "https://api.blockchain.info/charts/market-price"
    "?timespan=all&format=json&sampled=false"
)
USER_AGENT = "Mozilla/5.0 (compatible; bitcoin-price-models)"
DOWNLOAD_TIMEOUT_SECONDS = 30
BYTES_PER_MB = 1024 * 1024
MAX_DOWNLOAD_BYTES = 50 * BYTES_PER_MB
API_STATUS_KEY = "status"
API_STATUS_OK = "ok"
API_VALUES_KEY = "values"
MS_PER_SECOND = 1000

# Prompt handling and exit codes
YES_ANSWERS = ("y", "yes")
EXIT_FAILURE = 1

# Halvings cache and the mempool.space API used to build it
HALVINGS_FILE = os.path.join(DATA_DIR, "halvings.json")
MEMPOOL_TIP_HEIGHT_URL = "https://mempool.space/api/blocks/tip/height"
MEMPOOL_BLOCK_URL = "https://mempool.space/api/v1/blocks/{height}"
HALVING_INTERVAL_BLOCKS = 210_000
BLOCK_TIME_SECONDS = 600
# The genesis block timestamp and year 2100 bound any plausible block time
MIN_BLOCK_TIMESTAMP = 1_231_006_505
MAX_PLAUSIBLE_TIMESTAMP = 4_102_444_800
MAX_TIP_HEIGHT = 100 * HALVING_INTERVAL_BLOCKS

# Keys of the halvings cache and of the mempool.space block response
HALVINGS_PAST_KEY = "past"
HALVINGS_NEXT_KEY = "next"
HEIGHT_KEY = "height"
BLOCK_TIMESTAMP_KEY = "timestamp"
ESTIMATED_TIMESTAMP_KEY = "estimated_timestamp"
TIP_HEIGHT_KEY = "tip_height"
COMPUTED_AT_KEY = "computed_at"

# Power law fit: days are counted from the genesis block date
GENESIS_DATE = "2009-01-03"
FIT_DEGREE = 1
MIN_FIT_POINTS = 2

# Lightweight Charts library, downloaded once and cached
LWC_VERSION = "5.2.1"
LWC_URL = (
    f"https://cdn.jsdelivr.net/npm/lightweight-charts@{LWC_VERSION}"
    "/dist/lightweight-charts.standalone.production.js"
)
LWC_FILE = os.path.join(DATA_DIR, f"lightweight-charts-{LWC_VERSION}.js")
# A valid library build defines this global name
LWC_MARKER = "LightweightCharts"

# Chart page
CHART_TITLE = "Bitcoin Price Models"
MODE_GOLDEN = "golden"
MODE_POWER_LAW = "powerlaw"
MODES = (MODE_GOLDEN, MODE_POWER_LAW)
DATE_FORMAT = "%Y-%m-%d"
SCRIPT_CLOSE_TAG = "</"
SCRIPT_CLOSE_ESCAPED = "<\\/"
SCRIPT_COMMENT_OPEN = "<!--"
SCRIPT_COMMENT_ESCAPED = "<\\!--"
TEMPLATE_TITLE_KEY = "title"
TEMPLATE_LIB_KEY = "lib_js"
TEMPLATE_APP_KEY = "app_js"
TEMPLATE_PAYLOAD_KEY = "payload_json"

# Series keys and labels shared by the payload and the page legend
MOVING_AVERAGE_KEY = "ma"
MOVING_AVERAGE_LABEL = "350DMA"
FAIR_VALUE_KEY = "fair"
FAIR_VALUE_LABEL = "Power Law"
BAND_KEY_PREFIX = "x"
BAND_LABEL_SUFFIX = "x Multiplier"
HALVING_LABEL_PREFIX = "Halving"
NEXT_HALVING_LABEL_PREFIX = "Next halving (est.)"

# Data frame column names
DATE_COLUMN = "Date"
CLOSE_COLUMN = "Close"
MOVING_AVERAGE_COLUMN = "MA"

# Compact dollar formatting
BILLION = 1_000_000_000
MILLION = 1_000_000
THOUSAND = 1_000
TEN = 10
SMALL_DECIMALS = 2
LARGE_DECIMALS = 1
