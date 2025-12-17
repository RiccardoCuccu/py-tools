"""Browser Fetcher - Playwright-based browser automation for JavaScript-rendered Amazon pages"""

import asyncio
import logging
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout
import config
from utils import extract_asin, parse_price_text, parse_price_from_parts, BaseFetcher

logger = logging.getLogger(__name__)


class BrowserFetcher(BaseFetcher):
    """Fetches product data using browser automation with Playwright"""
    
    def __init__(self):
        """Initialize browser fetcher"""
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context = None
        self._initialized = False
        logger.info("[Browser] Fetcher initialized")
    
    @property
    def name(self) -> str:
        """Return human-readable fetcher name"""
        return "Browser Extractor"
    
    @property
    def stats_key(self) -> str:
        """Return unique key for statistics tracking"""
        return "browser"
    
    async def _ensure_initialized(self):
        """Ensure browser is initialized exactly once"""
        if not self._initialized:
            await self._initialize_browser()
            self._initialized = True
    
    async def _initialize_browser(self):
        """Initialize Playwright browser with configured settings"""
        if self._browser:
            return
        
        try:
            logger.info(f"[Browser] Initializing Playwright {config.BROWSER_TYPE}...")
            self._playwright = await async_playwright().start()
            
            if config.BROWSER_TYPE == 'chromium':
                browser_launcher = self._playwright.chromium
            elif config.BROWSER_TYPE == 'firefox':
                browser_launcher = self._playwright.firefox
            elif config.BROWSER_TYPE == 'webkit':
                browser_launcher = self._playwright.webkit
            else:
                raise ValueError(f"Invalid BROWSER_TYPE: {config.BROWSER_TYPE}")
            
            self._browser = await browser_launcher.launch(
                headless=config.BROWSER_HEADLESS,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                ]
            )
            
            self._context = await self._browser.new_context(
                viewport={
                    'width': config.BROWSER_VIEWPORT_WIDTH,
                    'height': config.BROWSER_VIEWPORT_HEIGHT
                },
                user_agent=config.USER_AGENTS[0],
                locale=config.BROWSER_LOCALE,
                timezone_id=config.BROWSER_TIMEZONE,
            )
            
            logger.info("[Browser] Playwright ready")
            
        except Exception as e:
            logger.error(f"[Browser] Initialization failed: {e}")
            await self.close()
            raise
    
    async def _set_delivery_address(self, page: Page) -> bool:
        """Set delivery address on Amazon to ensure correct product availability"""
        if not config.BROWSER_DELIVERY_POSTAL_CODE:
            return False
        
        try:
            postal_code = config.BROWSER_DELIVERY_POSTAL_CODE
            
            address_link = await page.query_selector(
                '#contextualIngressPtLink, #nav-global-location-popover-link, '
                '#glow-ingress-block, .nav-global-location-slot'
            )
            if not address_link:
                logger.debug("[Browser] Delivery address link not found")
                return False
            
            await address_link.click()
            await page.wait_for_timeout(1500)
            
            postal_input = await page.query_selector(
                '#GLUXZipUpdateInput, input[data-action="GLUXPostalInputAction"], '
                '#GLUXZipUpdateInput_0'
            )
            if not postal_input:
                logger.debug("[Browser] Postal code input not found")
                return False
            
            await postal_input.fill('')
            await postal_input.fill(postal_code)
            
            apply_btn = await page.query_selector(
                '#GLUXZipUpdate, [data-action="GLUXPostalUpdateAction"] input[type="submit"], '
                '#GLUXZipUpdate input, .a-button-input[aria-labelledby*="GLUXZipUpdate"]'
            )
            if apply_btn:
                await apply_btn.click()
                await page.wait_for_timeout(2000)
                logger.info(f"[Browser] Delivery address set to: {postal_code}")
                return True
            
            return False
            
        except Exception as e:
            logger.debug(f"[Browser] Delivery address setting failed: {e}")
            return False
    
    async def _extract_from_hidden_input(self, page: Page) -> Optional[float]:
        """Extract price from hidden input field"""
        try:
            hidden_input = await page.wait_for_selector(
                'input[name*="customerVisiblePrice"][name*="amount"]',
                timeout=5000,
                state='attached'
            )
            
            if hidden_input:
                price_value = await hidden_input.get_attribute('value')
                if price_value:
                    price_str = price_value.strip().replace(',', '.')
                    try:
                        price = float(price_str)
                        if config.MIN_VALID_PRICE <= price <= config.MAX_VALID_PRICE:
                            return price
                    except ValueError:
                        pass
        except PlaywrightTimeout:
            pass
        except Exception as e:
            logger.debug(f"[Browser] Hidden input extraction failed: {e}")
        
        return None
    
    async def _extract_price_from_element(self, price_element) -> Optional[float]:
        """Extract price from a-price element"""
        try:
            offscreen = await price_element.query_selector('span.a-offscreen')
            if offscreen:
                text = await offscreen.inner_text()
                price = parse_price_text(text)
                if price:
                    return price
            
            whole_elem = await price_element.query_selector('span.a-price-whole')
            fraction_elem = await price_element.query_selector('span.a-price-fraction')
            
            if whole_elem and fraction_elem:
                whole_text = await whole_elem.inner_text()
                fraction_text = await fraction_elem.inner_text()
                return parse_price_from_parts(whole_text, fraction_text)
                
        except Exception as e:
            logger.debug(f"[Browser] Element extraction failed: {e}")
        
        return None
    
    async def _try_extract_from_container(self, container, expected_asin: Optional[str], selector: str) -> Optional[float]:
        """Try extracting price from a single container"""
        if expected_asin and selector == '#corePrice_feature_div':
            actual_asin = await container.get_attribute('data-csa-c-asin')
            if actual_asin and actual_asin != expected_asin:
                return None
        
        price_span = await container.query_selector('span.a-price')
        return await self._extract_price_from_element(price_span) if price_span else None
    
    async def _extract_from_visible_elements(self, page: Page, expected_asin: Optional[str]) -> Optional[float]:
        """Extract price from visible elements"""
        containers = [
            '#corePrice_feature_div',
            '#corePriceDisplay_desktop_feature_div',
            '#apex_desktop',
        ]
        
        for selector in containers:
            try:
                container = await page.query_selector(selector)
                if container:
                    price = await self._try_extract_from_container(container, expected_asin, selector)
                    if price:
                        return price
                        
            except Exception as e:
                logger.debug(f"[Browser] Container extraction failed ({selector}): {e}")
        
        return None
    
    async def _extract_price(self, page: Page, expected_asin: Optional[str]) -> Optional[float]:
        """Extract price using multiple methods"""
        price = await self._extract_from_hidden_input(page)
        if price:
            logger.debug("[Browser] Price extracted from hidden input")
            return price
        
        price = await self._extract_from_visible_elements(page, expected_asin)
        if price:
            logger.debug("[Browser] Price extracted from visible elements")
            return price
        
        return None
    
    async def fetch(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch product data using browser automation"""
        await self._ensure_initialized()
        
        if self._context is None:
            raise RuntimeError("[Browser] Context not initialized properly")
        
        expected_asin = extract_asin(url)
        page: Optional[Page] = None
        
        try:
            page = await self._context.new_page()
            await page.goto(url, wait_until='domcontentloaded', timeout=config.BROWSER_PAGE_TIMEOUT)
            
            try:
                async with asyncio.timeout(config.BROWSER_PAGE_TIMEOUT / 1000):
                    if config.BROWSER_DELIVERY_POSTAL_CODE:
                        success = await self._set_delivery_address(page)
                        if not success:
                            logger.warning(f"[Browser] Delivery address setting failed for: {url}")
                    
                    price = await self._extract_price(page, expected_asin)
            except asyncio.TimeoutError:
                logger.error(f"[Browser] Page operations timed out: {url}")
                return None
            
            name = None
            image_url = None
            
            try:
                title_elem = await page.query_selector('span#productTitle')
                if title_elem:
                    name = (await title_elem.inner_text()).strip()
                
                img_selectors = ['img#landingImage', 'img#imgBlkFront']
                for selector in img_selectors:
                    img_elem = await page.query_selector(selector)
                    if img_elem:
                        image_url = await img_elem.get_attribute('data-old-hires')
                        if not image_url:
                            image_url = await img_elem.get_attribute('src')
                        if image_url and image_url.startswith('http'):
                            break
            except Exception as e:
                logger.debug(f"[Browser] Name/image extraction failed: {e}")
            
            if name:
                logger.info(f"[Browser] Retrieved: {name[:80]}...")
            if price:
                logger.info(f"[Browser] Price: {config.CURRENCY_SYMBOL}{price:.2f}")
            if image_url:
                logger.debug(f"[Browser] Image URL: {image_url[:60]}...")
            
            return {'price': price, 'name': name, 'image_url': image_url}
            
        except PlaywrightTimeout:
            logger.error(f"[Browser] Page load timed out: {url}")
            return None
        except Exception as e:
            logger.error(f"[Browser] Fetch failed: {e}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
    
    async def close(self):
        """Cleanup browser resources"""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            logger.debug("[Browser] Resources cleaned up")
        except Exception as e:
            logger.error(f"[Browser] Cleanup failed: {e}")