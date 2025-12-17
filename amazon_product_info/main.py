"""Amazon Product Info - standalone program to extract prices and product info from Amazon URLs"""

import asyncio
import logging
import sys
import time
import random
from pathlib import Path
from typing import List, Optional
import config
from utils import (
    ProductResult, ScraperStats, 
    process_amazon_url, extract_asin, is_short_url, expand_short_url,
    safe_close
)
from image_downloader import ImageDownloader
from fetcher_html import HTTPSessionManager

logger = logging.getLogger(__name__)

fetcher_api = None
fetcher_html = None
fetcher_browser = None

if config.ENABLE_FETCHER_API:
    from fetcher_api import APIFetcher
    fetcher_api = APIFetcher
    
if config.ENABLE_FETCHER_HTML:
    from fetcher_html import HTMLFetcher
    fetcher_html = HTMLFetcher
    
if config.ENABLE_FETCHER_BROWSER:
    from fetcher_browser import BrowserFetcher
    fetcher_browser = BrowserFetcher

logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('scraper.log', encoding='utf-8')
    ]
)


# ============================================================================
# MAIN SCRAPER CLASS
# ============================================================================

class AmazonScraper:
    """Main scraper class that orchestrates URL processing"""
    
    FETCHER_MAP = {
        'api': (fetcher_api, 'api', 'PA-API'),
        'html': (fetcher_html, 'html', 'HTML Scraper'),
        'browser': (fetcher_browser, 'browser', 'Browser Extractor')
    }
    
    def __init__(self):
        """Initialize scraper with configured fetchers"""
        self.image_downloader = ImageDownloader()
        self.stats = ScraperStats()
        self.fetchers = []
        
        for fetcher_name in config.FETCHER_ORDER:
            if fetcher_name not in self.FETCHER_MAP:
                continue
            
            fetcher_class, stats_key, display_name = self.FETCHER_MAP[fetcher_name]
            if not fetcher_class:
                continue
            
            try:
                fetcher = fetcher_class()
                self.fetchers.append(fetcher)
                self.stats.add_fetcher(stats_key, display_name)
            except Exception as e:
                logger.error(f"[Main] Fetcher initialization failed ({display_name}): {e}")
        
        if not self.fetchers:
            logger.error("[Main] No fetchers enabled - check config.py")
            sys.exit(1)
            
        logger.info(f"[Main] Initialized with {len(self.fetchers)} fetcher(s): {', '.join(config.FETCHER_ORDER)}")
    
    async def fetch_product_data_with_retry(self, url: str, max_retries: Optional[int] = None) -> Optional[dict]:
        """Fetch product data with retry logic and exponential backoff"""
        if max_retries is None:
            max_retries = config.MAX_HTTP_RETRIES
        
        for attempt in range(max_retries):
            result = await self.fetch_product_data(url)
            
            if result is not None:
                return result
            
            if attempt < max_retries - 1:
                delay = random.uniform(config.RETRY_DELAY_MIN, config.RETRY_DELAY_MAX) * (attempt + 1)
                logger.info(f"[Main] Retrying in {delay:.1f}s (attempt {attempt + 2}/{max_retries})...")
                await asyncio.sleep(delay)
        
        logger.error(f"[Main] All retry attempts exhausted for: {url}")
        return None
    
    async def fetch_product_data(self, url: str) -> Optional[dict]:
        """Fetch product data using configured fetchers in order"""
        for fetcher in self.fetchers:
            stats_key = fetcher.stats_key
            
            if stats_key not in self.stats.fetchers:
                logger.error(f"[Main] Unknown stats key '{stats_key}' - skipping fetcher")
                continue
            
            fetcher_stats = self.stats.fetchers[stats_key]
            
            try:
                fetcher_stats.attempts += 1
                logger.info(f"[Main] Attempting {fetcher_stats.name}...")
                
                data = await fetcher.fetch(url)
                
                if data is None:
                    fetcher_stats.failures += 1
                    fetcher_stats.last_error = "Fetch returned None"
                    logger.warning(f"[Main] Fetch failed ({fetcher_stats.name}): returned None")
                    continue
                
                if data.get('price') and data.get('name'):
                    fetcher_stats.successes += 1
                    fetcher_stats.last_error = None
                    logger.info(f"[Main] Fetch succeeded ({fetcher_stats.name}): {data.get('name')[:80]}...")
                    return data
                else:
                    fetcher_stats.failures += 1
                    fetcher_stats.last_error = "Missing price or name"
                    logger.warning(f"[Main] Fetch incomplete ({fetcher_stats.name}): missing price or name")
                    
            except Exception as e:
                fetcher_stats.failures += 1
                fetcher_stats.last_error = str(e)
                logger.error(f"[Main] Fetch error ({fetcher_stats.name}): {e}")
        
        logger.error("[Main] All fetchers exhausted")
        return None
    
    async def process_batch_with_api(self, urls: List[str]) -> dict:
        """Process batch of URLs using PA-API if available"""
        if not self.fetchers or self.fetchers[0].stats_key != 'api':
            return {}
        
        api_fetcher = self.fetchers[0]
        
        if not hasattr(api_fetcher, 'fetch_batch'):
            return {}
        
        stats_key = 'api'
        
        try:
            logger.info(f"[Main] Processing batch of {len(urls)} URLs with PA-API...")
            results = await api_fetcher.fetch_batch(urls)
            
            successful_count = 0
            for url, data in results.items():
                self.stats.fetchers[stats_key].attempts += 1
                if data and data.get('price') and data.get('name'):
                    self.stats.fetchers[stats_key].successes += 1
                    successful_count += 1
                    logger.info(f"[Main] Batch fetch succeeded: {data.get('name')[:80]}...")
                else:
                    self.stats.fetchers[stats_key].failures += 1
            
            if successful_count < len(urls):
                failed_count = len(urls) - successful_count
                logger.warning(f"[Main] Batch API partial success: {successful_count}/{len(urls)} succeeded, {failed_count} will use fallback")
            
            return results
            
        except Exception as e:
            logger.error(f"[Main] Batch fetch failed: {e}")
            return {}
    
    async def process_url(self, url: str) -> ProductResult:
        """Process single URL and return ProductResult"""
        cleaned_url = process_amazon_url(url)
        if not cleaned_url:
            logger.warning(f"[Main] URL validation failed: {url}")
            return ProductResult(url, None, None, None, None)
        
        logger.info(f"[Main] Processing: {cleaned_url}")
        
        product_data = await self.fetch_product_data_with_retry(cleaned_url)
        
        if not product_data:
            logger.warning(f"[Main] Data fetch failed: {cleaned_url}")
            return ProductResult(url, cleaned_url, None, None, None)
        
        return ProductResult(
            url,
            cleaned_url,
            product_data.get('price'),
            product_data.get('name'),
            product_data.get('image_url')
        )
    
    def _is_valid_url_line(self, line: str) -> bool:
        """Quick validation that line looks like an Amazon URL"""
        return any(domain in line.lower() for domain in ['amazon.', 'amzn.'])
    
    async def _expand_short_urls_batch(self, urls: List[str]) -> List[str]:
        """Expand all short URLs in parallel"""
        async def expand_or_keep(url: str) -> str:
            if is_short_url(url):
                expanded = await asyncio.to_thread(expand_short_url, url)
                return expanded if expanded else url
            return url
        
        tasks = [expand_or_keep(url) for url in urls]
        return await asyncio.gather(*tasks)
    
    async def _download_images_batch(self, results: List[ProductResult]):
        """Download all images in parallel at the end"""
        image_tasks = []
        
        for result in results:
            if result.image_url and result.cleaned_url:
                asin = extract_asin(result.cleaned_url)
                if asin:
                    image_tasks.append((asin, result.image_url))
        
        if not image_tasks:
            logger.info("[Main] No images to download")
            return
        
        logger.info(f"[Main] Downloading {len(image_tasks)} images in parallel...")
        
        tasks = [
            self.image_downloader.download_image(url, asin) 
            for asin, url in image_tasks
        ]
        
        download_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in download_results if r and not isinstance(r, Exception))
        logger.info(f"[Main] Image download complete: {success_count}/{len(image_tasks)} succeeded")
    
    async def _process_single_url_with_stats(self, url: str) -> ProductResult:
        """Process single URL and update statistics"""
        result = await self.process_url(url)
        self.stats.processed += 1
        
        if result.is_successful:
            self.stats.successful += 1
        else:
            self.stats.failed += 1
        
        return result
    
    async def _process_with_batching(self, urls: List[str]) -> List[ProductResult]:
        """Process URLs with batch API support"""
        results = []
        batch_size = config.API_BATCH_SIZE
        total_batches = (len(urls) + batch_size - 1) // batch_size
        
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]
            batch_num = i//batch_size + 1
            logger.info(f"{'='*100}")
            logger.info(f"[Main] Processing batch {batch_num}/{total_batches} ({len(batch)} URLs)")
            logger.info(f"{'='*100}")
            
            batch_results = await self.process_batch_with_api(batch)

            for idx, url in enumerate(batch):
                global_idx = i + idx + 1
                logger.info(f"{'='*100}")
                logger.info(f"[Main] Processing URL {global_idx}/{self.stats.total_urls}")

                if url in batch_results and batch_results[url]:
                    data = batch_results[url]
                    cleaned_url = process_amazon_url(url)
                    result = ProductResult(url, cleaned_url, data.get('price'), data.get('name'), data.get('image_url'))
                    results.append(result)
                    self.stats.processed += 1
                    if result.is_successful:
                        self.stats.successful += 1
                    else:
                        self.stats.failed += 1
                else:
                    result = await self._process_single_url_with_stats(url)
                    results.append(result)
                
                if global_idx < len(urls) and config.REQUEST_DELAY > 0:
                    await asyncio.sleep(config.REQUEST_DELAY)
                
        logger.info(f"{'='*100}")
        return results
    
    async def _process_sequential(self, urls: List[str]) -> List[ProductResult]:
        """Process URLs sequentially"""
        results = []
        
        for idx, url in enumerate(urls, 1):
            logger.info(f"\n{'='*100}\n[Main] Processing URL {idx}/{self.stats.total_urls}\n{'='*100}")
            
            result = await self._process_single_url_with_stats(url)
            results.append(result)
            
            if idx < len(urls) and config.REQUEST_DELAY > 0:
                await asyncio.sleep(config.REQUEST_DELAY)
        
        return results
    
    async def process_file(self, input_file: str, output_file: str):
        """Process input file and write results to output file"""
        input_path = Path(input_file)
        output_path = Path(output_file)
        
        if not input_path.exists():
            logger.error(f"[Main] Input file not found: {input_file}")
            return
        
        logger.info(f"[Main] Reading URLs from: {input_file}")
        with open(input_path, 'r', encoding='utf-8') as f:
            all_lines = [line.strip() for line in f]
        
        urls = []
        invalid_lines = []
        comment_count = 0
        
        for line in all_lines:
            if not line or line.startswith('#'):
                if line.startswith('#'):
                    comment_count += 1
                continue
            if self._is_valid_url_line(line):
                urls.append(line)
            else:
                invalid_lines.append(line)
        
        self.stats.total_urls = len(urls)
        logger.info(f"[Main] Found {self.stats.total_urls} valid URLs")
        logger.info(f"[Main] Ignored {comment_count} comment lines")
        if invalid_lines:
            logger.warning(f"[Main] Skipped {len(invalid_lines)} invalid URL lines")
            for invalid in invalid_lines[:5]:
                logger.warning(f"[Main]   - {invalid}")
            if len(invalid_lines) > 5:
                logger.warning(f"[Main]   ... and {len(invalid_lines) - 5} more")
        
        if any(is_short_url(url) for url in urls):
            logger.info("[Main] Expanding short URLs in parallel...")
            urls = await self._expand_short_urls_batch(urls)
        
        self.stats.start_time = time.time()
        
        if config.ENABLE_API_BATCH_REQUESTS and self.fetchers and self.fetchers[0].stats_key == 'api':
            results = await self._process_with_batching(urls)
        else:
            results = await self._process_sequential(urls)
        
        self.stats.end_time = time.time()
        
        logger.info(f"\n[Main] Writing results to: {output_file}")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# Amazon Product Data Export\n")
            f.write(f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("# Format: cleaned_url | price | product_name\n")
            f.write("#" + "="*100 + "\n\n")
            
            for result in results:
                if result.is_successful:
                    price_str = f"{config.CURRENCY_SYMBOL}{result.price:.2f}"
                    f.write(f"{result.cleaned_url} | {price_str} | {result.name}\n")
                elif result.cleaned_url:
                    f.write(f"{result.cleaned_url} | N/A | N/A\n")
                else:
                    f.write(f"# FAILED: {result.original_url}\n")
        
        if config.ENABLE_IMAGE_DOWNLOAD:
            await self._download_images_batch(results)
        
        self._print_summary(output_file)
    
    def _print_summary(self, output_file: str):
        """Print detailed summary statistics"""
        print("\n" + "="*100)
        print("SCRAPING SUMMARY")
        print("="*100)
        print(f"\nOverall Statistics:")
        print(f"  - Total URLs processed: {self.stats.processed}/{self.stats.total_urls}")
        print(f"  - Successful extractions: {self.stats.successful} ({self.stats.successful/self.stats.total_urls*100:.1f}%)")
        print(f"  - Failed extractions: {self.stats.failed} ({self.stats.failed/self.stats.total_urls*100:.1f}%)")
        print(f"  - Total duration: {self.stats.duration:.1f}s ({self.stats.duration/self.stats.total_urls:.1f}s per URL)")
        
        print(f"\nFetcher Performance:")
        for key, stats in self.stats.fetchers.items():
            print(f"  - {stats.name}:")
            print(f"      Attempts: {stats.attempts}")
            print(f"      Successes: {stats.successes}")
            print(f"      Failures: {stats.failures}")
            print(f"      Success Rate: {stats.success_rate:.1f}%")
            if stats.last_error:
                print(f"      Last Error: {stats.last_error}")
        
        if config.ENABLE_IMAGE_DOWNLOAD:
            print(f"\nImages saved to: {self.image_downloader.output_dir}")
        
        print(f"\nResults saved to: {output_file}")
        print("="*100 + "\n")
    
    async def cleanup(self):
        """Cleanup resources with proper error handling"""
        for fetcher in self.fetchers:
            await safe_close(fetcher, fetcher.name)
        
        await HTTPSessionManager.close()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

async def main():
    """Main entry point"""
    if len(sys.argv) < 3:
        print("Usage: python main.py input.txt output.txt")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    print("\n" + "="*100)
    print("AMAZON PRODUCT PRICE SCRAPER")
    print("="*100)
    print(f"\nConfiguration:")
    print(f"  - Fetcher order: {' -> '.join(config.FETCHER_ORDER)}")
    if config.ENABLE_API_BATCH_REQUESTS:
        print(f"  - Batch API: enabled (size: {config.API_BATCH_SIZE})")
    print(f"  - Image download: {'enabled' if config.ENABLE_IMAGE_DOWNLOAD else 'disabled'}")
    print(f"  - Request delay: {config.REQUEST_DELAY}s")
    print(f"  - Retry attempts: {config.MAX_HTTP_RETRIES}")
    print(f"  - Target marketplace: {config.TARGET_MARKETPLACE}")
    print("="*100 + "\n")
    
    scraper = AmazonScraper()
    
    try:
        await scraper.process_file(input_file, output_file)
    finally:
        await scraper.cleanup()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n[Main] Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[Main] Fatal error: {e}", exc_info=True)
        sys.exit(1)