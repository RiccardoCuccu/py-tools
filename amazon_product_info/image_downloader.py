"""Image Downloader - downloads and saves product images with ASIN-based naming using shared HTTP session"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ImageDownloader:
    """Manages product image downloads using async I/O and shared HTTP session"""
    
    def __init__(self, output_dir: str = "images"):
        """Initialize image downloader with output directory"""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9",
            "Referer": "https://www.amazon.it/",
        }
    
    async def download_image(self, image_url: str, asin: str, max_retries: int = 3) -> Optional[str]:
        """Download image asynchronously with retry logic and exponential backoff"""
        from fetcher_html import HTTPSessionManager
        
        safe_asin = re.sub(r'[^\w\-]', '_', asin)
        if not safe_asin:
            logger.error("[Image] ASIN sanitization resulted in empty filename")
            return None
        
        filepath = self.output_dir / f"{safe_asin}.jpg"
        
        for attempt in range(max_retries):
            try:
                logger.info(f"[Image] Downloading for {safe_asin} (attempt {attempt + 1}/{max_retries})")
                
                session = await HTTPSessionManager.get_session()
                async with session.get(image_url, headers=self.headers) as response:
                    response.raise_for_status()
                    content = await response.read()
                
                try:
                    await asyncio.to_thread(self._write_file_safe, filepath, content)
                    logger.info(f"[Image] Saved: {filepath} ({len(content)} bytes)")
                    return str(filepath)
                except IOError as e:
                    logger.error(f"[Image] File write failed: {e}")
                    return None
                
            except Exception as e:
                logger.warning(f"[Image] Download attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    delay = 2 ** attempt
                    logger.info(f"[Image] Retrying in {delay}s...")
                    await asyncio.sleep(delay)
        
        logger.error(f"[Image] Download failed for {safe_asin} after {max_retries} attempts")
        return None
    
    def _write_file_safe(self, filepath: Path, content: bytes):
        """Safely write file with proper error handling"""
        try:
            with open(filepath, 'wb') as f:
                f.write(content)
        except OSError as e:
            raise IOError(f"Failed to write image file: {e}")