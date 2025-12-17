"""Shared utilities - all helper functions, data models, and common utilities for the scraper"""

import asyncio
import logging
import re
import requests
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List
import sys

sys.path.insert(0, str(Path(__file__).parent))
import config

logger = logging.getLogger(__name__)

# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ProductResult:
    """Represents the result of processing a single product URL"""
    original_url: str
    cleaned_url: Optional[str]
    price: Optional[float]
    name: Optional[str]
    image_url: Optional[str]

    @property
    def is_successful(self) -> bool:
        """Check if product data was successfully extracted"""
        return self.cleaned_url is not None and self.price is not None and self.name is not None


@dataclass
class FetcherStats:
    """Statistics for a single fetcher"""
    name: str
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    last_error: Optional[str] = None

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage"""
        return (self.successes / self.attempts * 100) if self.attempts > 0 else 0.0


@dataclass
class ScraperStats:
    """Overall scraper statistics"""
    total_urls: int = 0
    processed: int = 0
    successful: int = 0
    failed: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    fetchers: Dict[str, FetcherStats] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        """Calculate total duration in seconds"""
        return self.end_time - self.start_time if self.end_time > 0 else 0.0

    def add_fetcher(self, key: str, name: str):
        """Add a fetcher to statistics tracking"""
        self.fetchers[key] = FetcherStats(name=name)


# ============================================================================
# ABSTRACT BASE CLASS
# ============================================================================

class BaseFetcher(ABC):
    """Abstract base class defining the interface for all product data fetchers"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return human-readable fetcher name"""
        pass

    @property
    @abstractmethod
    def stats_key(self) -> str:
        """Return unique key for statistics tracking"""
        pass

    @abstractmethod
    async def fetch(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch product data for a single URL and return dict with price, name, image_url keys"""
        pass

    async def fetch_batch(self, urls: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """Fetch product data for multiple URLs, default implementation calls fetch() sequentially"""
        results = {}
        for url in urls:
            results[url] = await self.fetch(url)
        return results

    async def close(self):
        """Cleanup resources, override if fetcher requires cleanup"""
        pass


# ============================================================================
# PRICE PARSING UTILITIES
# ============================================================================

def parse_price_text(text: str) -> Optional[float]:
    """Parse price from text like '44,95€' or '$19.99' and validate range"""
    if not text:
        return None
        
    try:
        cleaned = re.sub(r'[€$£¥₹₺\s]', '', text.strip())
        
        if re.match(r'^\d+,\d{2}$', cleaned):
            cleaned = cleaned.replace(',', '.')
        elif ',' in cleaned and '.' in cleaned:
            cleaned = cleaned.replace('.', '').replace(',', '.')
        
        price = float(cleaned)
        return price if config.MIN_VALID_PRICE <= price <= config.MAX_VALID_PRICE else None
        
    except (ValueError, AttributeError):
        return None


def parse_price_from_parts(whole: str, fraction: str) -> Optional[float]:
    """Parse price from separate whole and fraction parts like '44' and '95'"""
    if not whole or not fraction:
        return None
        
    try:
        whole_clean = whole.strip().replace(',', '').replace('.', '').replace(' ', '')
        fraction_clean = fraction.strip()
        
        if not whole_clean or not fraction_clean:
            return None
        
        price = float(f"{whole_clean}.{fraction_clean}")
        return price if config.MIN_VALID_PRICE <= price <= config.MAX_VALID_PRICE else None
        
    except ValueError:
        return None


def parse_price_flexible(text: Optional[str] = None, whole: Optional[str] = None, fraction: Optional[str] = None) -> Optional[float]:
    """Unified price parser supporting both text format and separate parts format"""
    if text:
        return parse_price_text(text)
    if whole and fraction:
        return parse_price_from_parts(whole, fraction)
    return None


# ============================================================================
# URL PROCESSING UTILITIES
# ============================================================================

def extract_asin(url: str) -> Optional[str]:
    """Extract 10-character ASIN from Amazon product URL using multiple patterns"""
    match = re.search(r'/dp/([A-Z0-9]{10})(?:/|$|\?)', url)
    if match:
        return match.group(1)
    
    match = re.search(r'/gp/product/([A-Z0-9]{10})', url)
    if match:
        return match.group(1)
    
    match = re.search(r'/gp/aw/d/([A-Z0-9]{10})(?:/|$|\?)', url)
    if match:
        return match.group(1)
    
    match = re.search(r'[?&]ASIN=([A-Z0-9]{10})', url)
    if match:
        return match.group(1)
    
    return None


def is_short_url(url: str) -> bool:
    """Check if URL is an Amazon short URL that needs expansion"""
    return any(domain in url.lower() for domain in config.SHORT_URL_DOMAINS)


def extract_domain(url: str) -> Optional[str]:
    """Extract Amazon domain from URL like 'amazon.it' or 'amazon.co.uk'"""
    match = re.search(r'amazon\.(co\.[a-z]{2}|com\.[a-z]{2}|[a-z]{2,3})', url, re.IGNORECASE)
    if match:
        return f"amazon.{match.group(1).lower()}"
    return None


def normalize_url(url: str) -> Optional[str]:
    """Normalize URL by adding https:// prefix if missing"""
    if url.startswith(('http://', 'https://')):
        return url
    
    if is_short_url(url):
        return f"https://{url}"
    elif url.startswith('amazon.'):
        return f"https://www.{url}"
    elif url.startswith('www.amazon.'):
        return f"https://{url}"
    
    return None


def expand_short_url(url: str, timeout: int = 10) -> Optional[str]:
    """Expand Amazon short URLs by following HTTP redirects"""
    if not is_short_url(url):
        return None
    
    normalized = normalize_url(url)
    if normalized:
        url = normalized
    
    try:
        logger.info(f"[URL] Expanding short URL: {url}")
        response = requests.get(url, allow_redirects=True, timeout=timeout, stream=True)
        expanded_url = response.url
        response.close()
        logger.info(f"[URL] Expanded to: {expanded_url}")
        return expanded_url
    except requests.RequestException as e:
        logger.error(f"[URL] Short URL expansion failed: {e}")
        return None


def process_amazon_url(url: str) -> Optional[str]:
    """Validate, expand, and sanitize Amazon URL returning clean format or None"""
    normalized = normalize_url(url)
    if normalized:
        url = normalized
    
    if is_short_url(url):
        expanded = expand_short_url(url)
        if not expanded:
            return None
        url = expanded
    
    asin = extract_asin(url)
    domain = extract_domain(url)
    
    if not asin or not domain:
        return None
    
    return f"https://{domain}/dp/{asin}"


# ============================================================================
# SHARED HELPER FUNCTIONS
# ============================================================================

async def safe_close(resource: Any, resource_name: str):
    """Safely close async resource with error logging"""
    if resource:
        try:
            await resource.close()
            logger.debug(f"[{resource_name}] Closed successfully")
        except Exception as e:
            logger.error(f"[{resource_name}] Cleanup failed: {e}")