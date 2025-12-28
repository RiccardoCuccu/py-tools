"""
Threads Follower Scraper
Extracts follower count from Threads profile URLs by parsing hidden JSON data
"""

import json
import re
import time
import os
import requests
from typing import Optional, Dict
from urllib.parse import urlparse

def extract_username(url: str) -> str:
    """Extract username from Threads URL"""
    # Threads URLs: threads.com/@username
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    username = path.split('/')[-1] if path else ""
    return username.lstrip('@')

def debug_log(message: str, debug_mode: bool = False) -> None:
    """Print debug message if debug mode is enabled"""
    if debug_mode:
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[DEBUG {timestamp}] Threads: {message}")

def extract_hidden_data(html: str, debug_mode: bool = False) -> Optional[dict]:
    """Extract hidden JSON data from Threads page"""
    # Look for the hidden data script tag
    pattern = r'<script type="application/json" data-content-len="[^"]*" data-sjs>\s*({.+?})\s*</script>'
    match = re.search(pattern, html, re.DOTALL)
    
    if not match:
        debug_log("Hidden JSON data not found", debug_mode)
        return None
    
    try:
        json_str = match.group(1)
        data = json.loads(json_str)
        debug_log("Successfully parsed hidden JSON data", debug_mode)
        return data
    except json.JSONDecodeError as e:
        debug_log(f"JSON decode error: {e}", debug_mode)
        return None

def find_follower_count(data: dict, debug_mode: bool = False) -> Optional[int]:
    """Recursively search for follower count in the data structure"""
    
    def recursive_search(obj, path=""):
        """Recursively search through nested dictionaries and lists"""
        if isinstance(obj, dict):
            # Check for follower_count key
            if 'follower_count' in obj:
                count = obj['follower_count']
                if isinstance(count, int):
                    debug_log(f"Found follower_count at path: {path}", debug_mode)
                    return count
            
            # Recursively search all dictionary values
            for key, value in obj.items():
                result = recursive_search(value, f"{path}.{key}")
                if result is not None:
                    return result
        
        elif isinstance(obj, list):
            # Recursively search all list items
            for i, item in enumerate(obj):
                result = recursive_search(item, f"{path}[{i}]")
                if result is not None:
                    return result
        
        return None
    
    result = recursive_search(data)
    
    if result is None:
        debug_log("follower_count not found in data structure", debug_mode)
    
    return result

def get_followers(url: str, max_retries: int = 3, retry_delay: int = 5, debug_mode: bool = False) -> Dict[str, Optional[int] | str]:
    """
    Get Threads follower count from profile URL
    
    Args:
        url: Threads profile URL (threads.com/@username)
        max_retries: Number of retry attempts
        retry_delay: Seconds to wait between retries
        debug_mode: Enable debug logging
    
    Returns:
        Dict with 'username' (str) and 'followers' (int or None) keys
    """
    username = extract_username(url)
    
    for attempt in range(max_retries):
        try:
            # Build Threads URL
            fetch_url = f"https://www.threads.com/@{username}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
            }
            
            debug_log(f"Fetching {fetch_url} (attempt {attempt + 1}/{max_retries})", debug_mode)
            response = requests.get(fetch_url, headers=headers, timeout=15)
            response.raise_for_status()
            debug_log(f"Response status {response.status_code}, length {len(response.text)}", debug_mode)
            
            # Extract hidden JSON data
            data = extract_hidden_data(response.text, debug_mode)
            
            if data:
                # Search for follower count in the data
                follower_count = find_follower_count(data, debug_mode)
                
                if follower_count is not None:
                    debug_log(f"Found {follower_count} followers for @{username}", debug_mode)
                    return {"username": username, "followers": follower_count}
            
            # Fallback: try regex patterns directly on HTML
            debug_log("Trying regex fallback patterns", debug_mode)
            patterns = [
                r'"follower_count"\s*:\s*(\d+)',
                r'follower_count["\s:]+(\d+)',
                r'"followers?"\s*:\s*(\d+)',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, response.text)
                if matches:
                    # Take the first reasonable match (not 0, not too large)
                    for match in matches:
                        count = int(match)
                        if 0 < count < 1000000000:  # Sanity check
                            debug_log(f"Found via regex: {count} followers", debug_mode)
                            return {"username": username, "followers": count}
            
            debug_log("No follower count found with any method", debug_mode)
            
            if debug_mode:
                # Save response for debugging
                script_dir = os.path.dirname(os.path.abspath(__file__))
                debug_dir = os.path.join(script_dir, "debug")
                os.makedirs(debug_dir, exist_ok=True)
                
                # Save HTML
                debug_file = os.path.join(debug_dir, f"threads_debug_attempt{attempt+1}.html")
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(response.text)
                debug_log(f"Response saved to {debug_file}", debug_mode)
                
                # Save extracted JSON if available
                if data:
                    json_file = os.path.join(debug_dir, f"threads_json_attempt{attempt+1}.json")
                    with open(json_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    debug_log(f"JSON data saved to {json_file}", debug_mode)
            
            if attempt < max_retries - 1:
                print(f"Threads: No data found for @{username} (attempt {attempt + 1}/{max_retries})")
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            
        except Exception as e:
            debug_log(f"Exception: {type(e).__name__}: {e}", debug_mode)
            
            if attempt < max_retries - 1:
                print(f"Threads error for @{username} (attempt {attempt + 1}/{max_retries}): {e}")
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"Threads error for @{username} after {max_retries} attempts: {e}")
                return {"username": username, "followers": None}
    
    return {"username": username, "followers": None}