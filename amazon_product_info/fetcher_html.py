"""HTML Fetcher - BeautifulSoup-based scraper with HTTP session management and all related functions"""

import asyncio
import logging
import random
import re
import aiohttp
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any
import config
from utils import extract_asin, parse_price_text, parse_price_from_parts, BaseFetcher

logger = logging.getLogger(__name__)


# ============================================================================
# HTTP SESSION MANAGER
# ============================================================================

class HTTPSessionManager:
    """Singleton HTTP session manager for efficient connection pooling"""

    _instance: Optional[aiohttp.ClientSession] = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        """Get or create the shared HTTP session with connection pooling"""
        if cls._instance is None or cls._instance.closed:
            async with cls._lock:
                if cls._instance is None or cls._instance.closed:
                    timeout = aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT)
                    connector = aiohttp.TCPConnector(
                        limit=100,
                        limit_per_host=10,
                        ttl_dns_cache=300
                    )
                    cls._instance = aiohttp.ClientSession(
                        timeout=timeout,
                        connector=connector
                    )
                    logger.debug("[HTTP] Shared session created")
        return cls._instance

    @classmethod
    async def close(cls):
        """Close the shared session and cleanup resources"""
        if cls._instance and not cls._instance.closed:
            await cls._instance.close()
            logger.debug("[HTTP] Shared session closed")


# ============================================================================
# HTML FETCHER CLASS
# ============================================================================

class HTMLFetcher(BaseFetcher):
    """Fetches product data using HTML scraping with BeautifulSoup"""
    
    def __init__(self):
        """Initialize HTML scraper"""
        logger.info("[HTML] Scraper initialized")
    
    @property
    def name(self) -> str:
        """Return human-readable fetcher name"""
        return "HTML Scraper"
    
    @property
    def stats_key(self) -> str:
        """Return unique key for statistics tracking"""
        return "html"
    
    def _get_random_headers(self) -> dict:
        """Generate HTTP headers with random User-Agent for anti-detection"""
        return {
            "User-Agent": random.choice(config.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        }
    
    def _is_captcha_page(self, soup: BeautifulSoup) -> bool:
        """Check if page is Amazon CAPTCHA or bot detection page"""
        captcha_indicators = [
            soup.find(string=re.compile(r'Robot Check|Enter the characters', re.I)),
            soup.find('form', {'action': re.compile(r'/errors/validateCaptcha', re.I)}),
            soup.find('img', {'src': re.compile(r'captcha', re.I)}),
        ]
        return any(captcha_indicators)
    
    def _extract_price(self, soup: BeautifulSoup, expected_asin: Optional[str]) -> Optional[float]:
        """Extract price from Amazon's corePrice container with ASIN verification"""
        core_price_div = soup.find("div", id="corePrice_feature_div")
        
        if not core_price_div:
            logger.debug("[HTML] corePrice_feature_div not found")
            return None
        
        if expected_asin:
            actual_asin = core_price_div.get("data-csa-c-asin")
            if actual_asin and actual_asin != expected_asin:
                logger.warning(f"[HTML] ASIN mismatch - expected: {expected_asin}, found: {actual_asin}")
                return None
        
        price_container = core_price_div.find("span", class_="a-price")
        if not price_container:
            logger.debug("[HTML] Price container not found")
            return None
        
        offscreen = price_container.find("span", class_="a-offscreen")
        if offscreen:
            price = parse_price_text(offscreen.get_text())
            if price:
                return price
        
        whole_elem = price_container.find("span", class_="a-price-whole")
        fraction_elem = price_container.find("span", class_="a-price-fraction")
        
        if whole_elem and fraction_elem:
            whole_text = ''.join(whole_elem.find_all(string=True, recursive=False))
            fraction_text = fraction_elem.get_text()
            return parse_price_from_parts(whole_text, fraction_text)
        
        return None
    
    def _extract_product_name(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract product name from HTML title element"""
        title = soup.find("span", {"id": "productTitle"})
        if title:
            return title.get_text().strip()
        return None
    
    def _extract_product_image(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract product image URL from HTML"""
        image_selectors = [
            ("img", {"id": "landingImage"}),
            ("img", {"id": "imgBlkFront"}),
            ("img", {"data-old-hires": True}),
        ]
        
        for tag, attrs in image_selectors:
            element = soup.find(tag, attrs)
            if element:
                img_url = element.get("data-old-hires") or element.get("src")
                if img_url and img_url.startswith("http"):
                    return img_url
        
        return None
    
    async def fetch(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch product data using HTML scraping"""
        expected_asin = extract_asin(url)
        
        try:
            session = await HTTPSessionManager.get_session()
            async with session.get(url, headers=self._get_random_headers()) as response:
                response.raise_for_status()
                html = await response.text()
                soup = BeautifulSoup(html, "lxml")
                
                if self._is_captcha_page(soup):
                    logger.warning("[HTML] CAPTCHA detected - scraping blocked")
                    return None
                
                price = self._extract_price(soup, expected_asin)
                name = self._extract_product_name(soup)
                image_url = self._extract_product_image(soup)
                
                if name:
                    logger.info(f"[HTML] Retrieved: {name[:80]}...")
                if price:
                    logger.info(f"[HTML] Price: {config.CURRENCY_SYMBOL}{price:.2f}")
                if image_url:
                    logger.debug(f"[HTML] Image URL: {image_url[:60]}...")
                
                return {'price': price, 'name': name, 'image_url': image_url}
                
        except Exception as e:
            logger.error(f"[HTML] Fetch failed: {e}")
            return None
    
    async def close(self):
        """Cleanup resources - session managed by HTTPSessionManager"""
        pass