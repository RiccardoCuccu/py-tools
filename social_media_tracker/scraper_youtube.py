"""
YouTube Subscriber Scraper using yt-dlp
Extracts subscriber count from YouTube channel URLs using yt-dlp
No API key required - completely free and unlimited
"""

import time
import os
from typing import Optional, Dict
from urllib.parse import urlparse

try:
    from yt_dlp import YoutubeDL  # type: ignore
    AVAILABLE = True
except ImportError:
    AVAILABLE = False
    YoutubeDL = None  # type: ignore

def extract_channel_url(url: str) -> str:
    """
    Normalize YouTube URL to channel format
    """
    # yt-dlp can handle various YouTube URL formats, just return as-is
    return url

def debug_log(message: str, debug_mode: bool = False) -> None:
    """Print debug message if debug mode is enabled"""
    if debug_mode:
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[DEBUG {timestamp}] YouTube: {message}")

def get_followers(url: str, max_retries: int = 3, retry_delay: int = 5, debug_mode: bool = False) -> Dict[str, Optional[int] | str]:
    """
    Get YouTube subscriber count using yt-dlp
    
    Args:
        url: YouTube channel URL
        max_retries: Number of retry attempts
        retry_delay: Seconds to wait between retries
        debug_mode: Enable debug logging
    
    Returns:
        Dict with 'username' (str) and 'followers' (int or None) keys
    """
    
    if not AVAILABLE:
        print("YouTube tracking disabled - yt-dlp not installed")
        print("Install with: pip install yt-dlp")
        return {"username": "", "followers": None}
    
    channel_url = extract_channel_url(url)
    
    for attempt in range(max_retries):
        try:
            debug_log(f"Fetching channel info from {channel_url} (attempt {attempt + 1}/{max_retries})", debug_mode)
            
            # Configure yt-dlp options
            ydl_opts: dict = {
                'quiet': True,  # Always quiet to suppress verbose output
                'no_warnings': True,
                'extract_flat': 'in_playlist',  # Don't extract individual videos in playlists
                'skip_download': True,
                'ignoreerrors': False,
                'playlist_items': '0',  # Don't process any playlist items
                'lazy_playlist': True,  # Don't load full playlist
            }
            
            with YoutubeDL(ydl_opts) as ydl:  # type: ignore
                if debug_mode:
                    debug_log("Extracting channel information...", debug_mode)
                info = ydl.extract_info(channel_url, download=False)
                
                if not info:
                    debug_log("No information returned", debug_mode)
                    if attempt < max_retries - 1:
                        print(f"YouTube: No data returned (attempt {attempt + 1}/{max_retries})")
                        print(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                    continue
                
                # Extract subscriber count
                subscriber_count = info.get('channel_follower_count')
                channel_name = info.get('channel', info.get('uploader', ''))
                channel_id = info.get('channel_id', '')
                
                if debug_mode:
                    debug_log(f"Channel: {channel_name}", debug_mode)
                    debug_log(f"Channel ID: {channel_id}", debug_mode)
                    debug_log(f"Subscriber count: {subscriber_count}", debug_mode)
                
                if subscriber_count is not None:
                    debug_log(f"Found {subscriber_count:,} subscribers for '{channel_name}'", debug_mode)
                    return {
                        "username": channel_name or channel_id,
                        "followers": int(subscriber_count)
                    }
                else:
                    debug_log("Subscriber count not available (may be hidden)", debug_mode)
                    print(f"YouTube: Subscriber count not available for this channel")
                    return {
                        "username": channel_name or channel_id or "Unknown",
                        "followers": None
                    }
            
        except Exception as e:
            debug_log(f"Exception: {type(e).__name__}: {e}", debug_mode)
            
            if "Private video" in str(e) or "This channel does not exist" in str(e):
                print(f"YouTube error: Channel not found or private - {e}")
                return {"username": "", "followers": None}
            
            if attempt < max_retries - 1:
                print(f"YouTube error (attempt {attempt + 1}/{max_retries}): {e}")
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"YouTube error after {max_retries} attempts: {e}")
                if debug_mode:
                    import traceback
                    traceback.print_exc()
                return {"username": "", "followers": None}
    
    return {"username": "", "followers": None}