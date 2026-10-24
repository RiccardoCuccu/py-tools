#!/usr/bin/env python3
"""
Amazon Product Price Scraper - Extract prices, names, and images from Amazon product URLs.

Tries up to three fetching methods in order (PA-API, HTML scraper, browser automation)
and writes results to an output file. Fetcher order and credentials are set in config.py.

Usage:
    python main.py input.txt output.txt
"""

import argparse
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

LOG_FORMAT = '%(levelname)s - %(message)s'
API_STATS_KEY = 'api'
EXIT_OK = 0
EXIT_ERROR = 1


def setup_logging():
    """Configure console and file logging (called from main, never at import time)"""
    logging.basicConfig(
        level=config.LOG_LEVEL,
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_FILE, encoding='utf-8')
        ]
    )


def load_fetcher_classes() -> dict:
    """Import only the fetchers enabled in config, so disabled ones need no dependencies"""
    classes = {}
    if config.ENABLE_FETCHER_API:
        from fetcher_api import APIFetcher
        classes['api'] = (APIFetcher, 'api', 'PA-API')
    if config.ENABLE_FETCHER_HTML:
        from fetcher_html import HTMLFetcher
        classes['html'] = (HTMLFetcher, 'html', 'HTML Scraper')
    if config.ENABLE_FETCHER_BROWSER:
        from fetcher_browser import BrowserFetcher
        classes['browser'] = (BrowserFetcher, 'browser', 'Browser Extractor')
    return classes


class AmazonScraper:
    """Main scraper class that orchestrates URL processing"""

    def __init__(self):
        """Initialize scraper with configured fetchers"""
        fetcher_map = load_fetcher_classes()
        self.image_downloader = ImageDownloader()
        self.stats = ScraperStats()
        self.fetchers = []

        for fetcher_name in config.FETCHER_ORDER:
            if fetcher_name not in fetcher_map:
                continue

            fetcher_class, stats_key, display_name = fetcher_map[fetcher_name]

            try:
                fetcher = fetcher_class()
                self.fetchers.append(fetcher)
                self.stats.add_fetcher(stats_key, display_name)
            except Exception as e:
                logger.error(f"[Main] Fetcher initialization failed ({display_name}): {e}")

        if not self.fetchers:
            logger.error("[Main] No fetchers enabled - check config.py")
            sys.exit(1)

        logger.info(f"[Main] Initialized with {len(self.fetchers)} fetcher(s): {', '.join(f.stats_key for f in self.fetchers)}")

    async def fetch_product_data_with_retry(self, url: str, max_retries: Optional[int] = None, exclude: frozenset = frozenset()) -> Optional[dict]:
        """Fetch product data with retry logic and exponential backoff"""
        if max_retries is None:
            max_retries = config.MAX_HTTP_RETRIES

        for attempt in range(max_retries):
            result = await self.fetch_product_data(url, exclude)

            if result is not None:
                return result

            if attempt < max_retries - 1:
                delay = random.uniform(config.RETRY_DELAY_MIN, config.RETRY_DELAY_MAX) * (attempt + 1)
                logger.info(f"[Main] Retrying in {delay:.1f}s (attempt {attempt + 2}/{max_retries})...")
                await asyncio.sleep(delay)

        logger.error(f"[Main] All retry attempts exhausted for: {url}")
        return None

    async def fetch_product_data(self, url: str, exclude: frozenset = frozenset()) -> Optional[dict]:
        """Fetch product data using configured fetchers in order, skipping excluded stats keys"""
        for fetcher in self.fetchers:
            stats_key = fetcher.stats_key

            if stats_key in exclude:
                continue

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
        if not self.fetchers or self.fetchers[0].stats_key != API_STATS_KEY:
            return {}

        api_fetcher = self.fetchers[0]

        if not hasattr(api_fetcher, 'fetch_batch'):
            return {}

        stats_key = API_STATS_KEY

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

    async def process_url(self, url: str, exclude: frozenset = frozenset()) -> ProductResult:
        """Process single URL and return ProductResult"""
        cleaned_url = process_amazon_url(url)
        if not cleaned_url:
            logger.warning(f"[Main] URL validation failed: {url}")
            return ProductResult(url, None, None, None, None)

        logger.info(f"[Main] Processing: {cleaned_url}")

        product_data = await self.fetch_product_data_with_retry(cleaned_url, exclude=exclude)

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

    async def _process_single_url_with_stats(self, url: str, exclude: frozenset = frozenset()) -> ProductResult:
        """Process single URL and update statistics"""
        result = await self.process_url(url, exclude)
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

                data = batch_results.get(url)
                # Incomplete batch data (e.g. no price) must fall through to the other fetchers
                if data and data.get('price') and data.get('name'):
                    cleaned_url = process_amazon_url(url)
                    result = ProductResult(url, cleaned_url, data.get('price'), data.get('name'), data.get('image_url'))
                    results.append(result)
                    self.stats.processed += 1
                    if result.is_successful:
                        self.stats.successful += 1
                    else:
                        self.stats.failed += 1
                else:
                    # The batch call already tried PA-API for this URL
                    result = await self._process_single_url_with_stats(url, frozenset({API_STATS_KEY}))
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

    async def process_file(self, input_file: str, output_file: str) -> bool:
        """Process input file and write results to output file, returning False if the input is missing"""
        input_path = Path(input_file)
        output_path = Path(output_file)

        if not input_path.exists():
            logger.error(f"[Main] Input file not found: {input_file}")
            return False

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

        if config.ENABLE_API_BATCH_REQUESTS and self.fetchers and self.fetchers[0].stats_key == API_STATS_KEY:
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
        return True

    def _print_summary(self, output_file: str):
        """Print detailed summary statistics"""
        total = max(self.stats.total_urls, 1)
        print("\n" + "="*100)
        print("SCRAPING SUMMARY")
        print("="*100)
        print(f"\nOverall Statistics:")
        print(f"  - Total URLs processed: {self.stats.processed}/{self.stats.total_urls}")
        print(f"  - Successful extractions: {self.stats.successful} ({self.stats.successful/total*100:.1f}%)")
        print(f"  - Failed extractions: {self.stats.failed} ({self.stats.failed/total*100:.1f}%)")
        print(f"  - Total duration: {self.stats.duration:.1f}s ({self.stats.duration/total:.1f}s per URL)")

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


async def main() -> int:
    """Main entry point, returns the process exit code"""
    parser = argparse.ArgumentParser(description="Extract prices and product info from Amazon URLs")
    parser.add_argument("input_file", help="Path to input file containing Amazon URLs")
    parser.add_argument("output_file", help="Path to output file for results")
    args = parser.parse_args()

    input_file = args.input_file
    output_file = args.output_file

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
        found = await scraper.process_file(input_file, output_file)
    finally:
        await scraper.cleanup()
    return EXIT_OK if found else EXIT_ERROR


if __name__ == '__main__':
    setup_logging()
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("\n[Main] Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[Main] Fatal error: {e}", exc_info=True)
        sys.exit(1)