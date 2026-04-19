#!/usr/bin/env python3
"""
Instagram Follower Scraper - Extracts follower count from public Instagram profiles without login.
"""

import json
import re
import time
from typing import Optional, Dict
from urllib.parse import urlparse, ParseResult

import requests

try:
    import selenium  # noqa: F401
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# Request headers mimicking a real browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
}

# Seconds to wait for JavaScript to render when using Selenium
SELENIUM_RENDER_WAIT = 5


def extract_username(url: str) -> str:
    """Extract username from Instagram profile URL."""
    parsed: ParseResult = urlparse(url)
    path = parsed.path.strip('/')
    return path.split('/')[-1] if path else ""


def debug_log(message: str, debug_mode: bool = False) -> None:
    """Print debug message if debug mode is enabled."""
    if debug_mode:
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[DEBUG {timestamp}] Instagram: {message}")


def _parse_follower_count(html: str, debug_mode: bool = False) -> Optional[int]:
    """
    Parse follower count from Instagram profile HTML.

    Uses precise patterns targeting edge_followed_by to avoid matching
    post counts, following counts, or other numeric values near "followers".
    """
    # Stage 1 - precise edge_followed_by regex (most reliable from embedded JS data)
    precise_patterns = [
        r'"edge_followed_by"\s*:\s*\{\s*"count"\s*:\s*(\d+)',
        r'"follower_count"\s*:\s*(\d+)',
    ]
    for pattern in precise_patterns:
        match = re.search(pattern, html)
        if match:
            count = int(match.group(1))
            if 0 < count < 1_000_000_000:
                debug_log(f"Found {count} followers via pattern: {pattern[:40]}", debug_mode)
                return count

    # Stage 2 - JSON-LD structured data (SEO injection for public profiles)
    ld_pattern = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)
    for match in ld_pattern.finditer(html):
        try:
            data = json.loads(match.group(1))
            stats = data.get("author", data).get("interactionStatistic", [])
            for stat in stats:
                interaction_type = stat.get("interactionType", "")
                if "FollowAction" in interaction_type or "follow" in interaction_type.lower():
                    count = stat.get("userInteractionCount")
                    if isinstance(count, int) and count >= 0:
                        debug_log(f"Found {count} followers via JSON-LD", debug_mode)
                        return count
        except (json.JSONDecodeError, AttributeError, TypeError):
            continue

    debug_log("No follower count found in HTML", debug_mode)
    return None


# App ID required by Instagram's internal API (stable public value)
INSTAGRAM_APP_ID = "936619743392459"


def _fetch_with_api(username: str, debug_mode: bool = False) -> Optional[int]:
    """
    Fetch follower count via Instagram's internal web profile API.

    Uses the i.instagram.com endpoint with the public app ID header.
    Returns follower count or None if blocked or unavailable.
    """
    api_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
    api_headers = {**HEADERS, "x-ig-app-id": INSTAGRAM_APP_ID}
    try:
        debug_log(f"Fetching via API: {api_url}", debug_mode)
        response = requests.get(api_url, headers=api_headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        count = data["data"]["user"]["edge_followed_by"]["count"]
        if isinstance(count, int) and count >= 0:
            debug_log(f"Found {count} followers via API", debug_mode)
            return count
    except Exception as e:
        debug_log(f"API fetch failed: {type(e).__name__}: {e}", debug_mode)
    return None


def _fetch_with_requests(url: str, debug_mode: bool = False) -> Optional[int]:
    """
    Fetch Instagram profile via requests and parse follower count.

    Returns follower count as int, or None if blocked or not found.
    """
    try:
        debug_log(f"Fetching {url} with requests", debug_mode)
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        debug_log(f"Response: {response.status_code}, {len(response.text)} bytes", debug_mode)
        return _parse_follower_count(response.text, debug_mode)
    except Exception as e:
        debug_log(f"requests fetch failed: {type(e).__name__}: {e}", debug_mode)
        return None


def _parse_follower_title(title: str, debug_mode: bool = False) -> Optional[int]:
    """
    Parse follower count from the span[title] attribute value.

    Instagram renders the title as a formatted number string (e.g. "1,390").
    Strips commas, dots and whitespace then converts to int.
    """
    try:
        # Remove thousands separators (comma or period) and whitespace
        cleaned = re.sub(r"[\s,.]", "", title.strip())
        count = int(cleaned)
        if count >= 0:
            debug_log(f"Parsed title '{title}' -> {count}", debug_mode)
            return count
    except ValueError:
        debug_log(f"Could not parse title value: '{title}'", debug_mode)
    return None


def _fetch_with_selenium(url: str, debug_mode: bool = False) -> Optional[int]:
    """
    Fetch Instagram follower count via headless Chrome using the span[title] selector.

    Instagram renders the exact follower count in a <span title="1,390"> element
    after JavaScript executes. This is the most reliable no-login method.
    Returns follower count or None.
    """
    if not SELENIUM_AVAILABLE:
        debug_log("Selenium not available - skipping browser fallback", debug_mode)
        return None

    driver = None
    try:
        from selenium.webdriver.chrome.webdriver import WebDriver as ChromeDriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService
        from selenium.webdriver.common.by import By
        from selenium.common.exceptions import NoSuchElementException
        from webdriver_manager.chrome import ChromeDriverManager

        debug_log(f"Fetching {url} with Selenium headless Chrome", debug_mode)
        options = ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--log-level=3")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(f"user-agent={HEADERS['User-Agent']}")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        service = ChromeService(ChromeDriverManager().install())
        driver = ChromeDriver(service=service, options=options)
        driver.get(url)
        time.sleep(SELENIUM_RENDER_WAIT)

        debug_log(f"Page loaded, {len(driver.page_source)} bytes", debug_mode)

        # Primary: span[title] holds the exact formatted follower count
        try:
            span = driver.find_element(By.CSS_SELECTOR, "span[title]")
            title_value = span.get_attribute("title")
            debug_log(f"span[title] value: '{title_value}'", debug_mode)
            if title_value is None:
                raise NoSuchElementException("span[title] attribute is None")
            count = _parse_follower_title(title_value, debug_mode)
            if count is not None:
                return count
        except NoSuchElementException:
            debug_log("span[title] not found, falling back to page source parsing", debug_mode)

        # Fallback: parse raw page source with regex patterns
        return _parse_follower_count(driver.page_source, debug_mode)

    except Exception as e:
        debug_log(f"Selenium fetch failed: {type(e).__name__}: {e}", debug_mode)
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def get_followers(url: str, max_retries: int = 3, retry_delay: int = 5, debug_mode: bool = False) -> Dict[str, Optional[int] | str]:
    """
    Get Instagram follower count from public profile URL without login.

    Tries requests first, then falls back to Selenium headless Chrome.

    Args:
        url: Instagram profile URL
        max_retries: Number of retry attempts
        retry_delay: Seconds to wait between retries
        debug_mode: Enable debug logging

    Returns:
        Dict with 'username' (str) and 'followers' (int or None) keys
    """
    username = extract_username(url)

    if not SELENIUM_AVAILABLE:
        print("Warning: selenium not installed - browser fallback unavailable.")
        print("Install with: pip install selenium")

    for attempt in range(max_retries):
        debug_log(f"Attempt {attempt + 1}/{max_retries} for @{username}", debug_mode)

        followers = _fetch_with_api(username, debug_mode)

        if followers is None:
            debug_log("API returned no result, trying requests", debug_mode)
            followers = _fetch_with_requests(url, debug_mode)

        if followers is None:
            debug_log("requests returned no result, trying Selenium", debug_mode)
            followers = _fetch_with_selenium(url, debug_mode)

        if followers is not None:
            return {"username": username, "followers": followers}

        if attempt < max_retries - 1:
            print(f"Instagram: No data for @{username} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
            time.sleep(retry_delay)
        else:
            print(f"Instagram: Could not retrieve follower count for @{username} after {max_retries} attempts.")

    return {"username": username, "followers": None}
