"""PA-API Fetcher - Amazon Product Advertising API 5.0 fetcher with all related functions"""

import logging
from typing import Optional, Dict, Any
import config
from utils import extract_asin, parse_price_flexible, BaseFetcher

logger = logging.getLogger(__name__)

try:
    from amazon_paapi import AmazonApi
    from amazon_paapi.models import Country
    PAAPI_AVAILABLE = True
except ImportError:
    AmazonApi = None
    Country = None
    PAAPI_AVAILABLE = False
    logger.warning("[PA-API] SDK not installed - install with: pip install python-amazon-paapi")


# ============================================================================
# PA-API FETCHER CLASS
# ============================================================================

class APIFetcher(BaseFetcher):
    """Fetches product data using Amazon Product Advertising API"""
    
    SUPPORTED_MARKETPLACES = ["IT", "US", "UK", "DE", "FR", "ES", "CA", "JP"]
    
    def __init__(self):
        """Initialize PA-API client with credentials from config"""
        if not PAAPI_AVAILABLE or AmazonApi is None or Country is None:
            raise ImportError("Amazon PA-API SDK required - install: pip install python-amazon-paapi")
        
        if not config.PA_API_ACCESS_KEY or not config.PA_API_SECRET_KEY:
            raise ValueError("PA-API credentials not configured in config.json")
        
        self.marketplace = config.TARGET_MARKETPLACE.upper()
        
        if self.marketplace not in self.SUPPORTED_MARKETPLACES:
            raise ValueError(f"Unsupported marketplace: {self.marketplace} (supported: {self.SUPPORTED_MARKETPLACES})")
        
        self.country = getattr(Country, self.marketplace)
        
        try:
            self.api = AmazonApi(
                key=config.PA_API_ACCESS_KEY,
                secret=config.PA_API_SECRET_KEY,
                tag="",
                country=self.country,
                throttling=config.PA_API_THROTTLING
            )
            logger.info(f"[PA-API] Client initialized for {self.marketplace} marketplace")
        except Exception as e:
            logger.error(f"[PA-API] Client initialization failed: {e}")
            raise
    
    @property
    def name(self) -> str:
        """Return human-readable fetcher name"""
        return "PA-API"
    
    @property
    def stats_key(self) -> str:
        """Return unique key for statistics tracking"""
        return "api"
    
    async def fetch(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch product data from PA-API for a single URL"""
        asin = extract_asin(url)
        if not asin:
            logger.error(f"[PA-API] ASIN extraction failed from URL: {url}")
            return None
        
        try:
            items = self.api.get_items(asin)
            
            if not items or len(items) == 0:
                logger.warning(f"[PA-API] No data returned for ASIN: {asin}")
                return None
            
            return self._extract_item_data(items[0])
            
        except Exception as e:
            logger.error(f"[PA-API] Fetch failed for ASIN {asin}: {e}")
            return None
    
    async def fetch_batch(self, urls: list[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """Fetch product data for multiple URLs in one API call (up to 10 URLs)"""
        if not urls or len(urls) > 10:
            raise ValueError("Batch size must be 1-10 URLs")
        
        url_to_asin = {}
        asins = []
        for url in urls:
            asin = extract_asin(url)
            if asin:
                url_to_asin[url] = asin
                asins.append(asin)
        
        if not asins:
            return {url: None for url in urls}
        
        try:
            items = self.api.get_items(*asins)
            
            asin_to_data = {
                item.asin: self._extract_item_data(item)
                for item in (items or [])
                if hasattr(item, 'asin')
            }
            
            return {url: asin_to_data.get(asin) for url, asin in url_to_asin.items()}
            
        except Exception as e:
            logger.error(f"[PA-API] Batch fetch failed: {e}")
            return {url: None for url in urls}
    
    def _extract_item_data(self, item) -> Optional[Dict[str, Any]]:
        """Extract product data from PA-API item object"""
        try:
            product_name = None
            if item.item_info and item.item_info.title and item.item_info.title.display_value:
                product_name = item.item_info.title.display_value
            
            price = None
            if item.offers and item.offers.listings and len(item.offers.listings) > 0:
                listing = item.offers.listings[0]
                if listing.price and listing.price.display_amount:
                    price_str = listing.price.display_amount
                    price = parse_price_flexible(text=price_str)
                    if price is None:
                        logger.warning(f"[PA-API] Price parsing failed: {price_str}")
            
            image_url = None
            
            if product_name:
                logger.debug(f"[PA-API] Retrieved: {product_name[:80]}...")
            if price:
                logger.debug(f"[PA-API] Price: {config.CURRENCY_SYMBOL}{price:.2f}")
            
            return {
                'price': price,
                'name': product_name,
                'image_url': image_url
            }
            
        except Exception as e:
            logger.error(f"[PA-API] Item data extraction failed: {e}")
            return None
    
    async def close(self):
        """Cleanup resources - PA-API client doesn't require cleanup"""
        pass