"""
Instagram Follower Scraper
Extracts follower count from Instagram profile URLs
"""

import time
import os
from typing import Optional, Dict
from urllib.parse import urlparse

try:
    import instaloader
    AVAILABLE = True
except ImportError:
    AVAILABLE = False
    instaloader = None  # type: ignore

def extract_username(url: str) -> str:
    """Extract username from Instagram URL"""
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    return path.split('/')[-1] if path else ""

def debug_log(message: str, debug_mode: bool = False) -> None:
    """Print debug message if debug mode is enabled"""
    if debug_mode:
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[DEBUG {timestamp}] Instagram: {message}")

def get_followers(url: str, max_retries: int = 3, retry_delay: int = 5, debug_mode: bool = False) -> Dict[str, Optional[int] | str]:
    """
    Get Instagram follower count from profile URL
    
    Args:
        url: Instagram profile URL
        max_retries: Number of retry attempts
        retry_delay: Seconds to wait between retries
        debug_mode: Enable debug logging
    
    Returns:
        Dict with 'username' (str) and 'followers' (int or None) keys
    """
    username = extract_username(url)
    
    if not AVAILABLE or instaloader is None:
        print("Instagram tracking disabled - instaloader not installed")
        print("Install with: pip install instaloader")
        return {"username": username, "followers": None}
    
    for attempt in range(max_retries):
        try:
            debug_log(f"Fetching profile for @{username} (attempt {attempt + 1}/{max_retries})", debug_mode)
            
            L = instaloader.Instaloader()
            profile = instaloader.Profile.from_username(L.context, username)
            followers = profile.followers
            
            debug_log(f"Found {followers} followers for @{username}", debug_mode)
            return {"username": username, "followers": followers}
            
        except Exception as e:
            debug_log(f"Error: {type(e).__name__}: {e}", debug_mode)
            
            if debug_mode:
                # Save error details for debugging
                script_dir = os.path.dirname(os.path.abspath(__file__))
                debug_dir = os.path.join(script_dir, "debug")
                os.makedirs(debug_dir, exist_ok=True)
                debug_file = os.path.join(debug_dir, "instagram_debug.txt")
                with open(debug_file, "a", encoding="utf-8") as f:
                    from datetime import datetime
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] Attempt {attempt + 1}/{max_retries} for @{username}\n")
                    f.write(f"Error: {type(e).__name__}: {e}\n\n")
                debug_log(f"Error logged to {debug_file}", debug_mode)
            
            if attempt < max_retries - 1:
                print(f"Instagram error for @{username} (attempt {attempt + 1}/{max_retries}): {e}")
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"Instagram error for @{username} after {max_retries} attempts: {e}")
                return {"username": username, "followers": None}
    
    return {"username": username, "followers": None}