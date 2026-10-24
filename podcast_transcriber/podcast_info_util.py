#!/usr/bin/env python3
"""
podcast_info_util.py - Extract podcast ID and episode title from an Apple Podcasts URL.
"""

import re
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup, Tag

HTTP_OK = 200
REQUEST_TIMEOUT_SECONDS = 30

# Matches https://podcasts.apple.com/<country>/podcast/<slug>/id<digits>?i=<episode>
APPLE_PODCAST_URL_PATTERN = re.compile(
    r"^https?://podcasts\.apple\.com/(?:[A-Za-z]{2}/)?podcast/(?:(?P<slug>[^/?#]+)/)?id(?P<id>\d+)",
    re.IGNORECASE,
)
TITLE_SEPARATOR = " - "


def parse_podcast_url(podcast_url):
    """Return (podcast_id, slug_title) from an Apple Podcasts URL, or raise ValueError.

    The slug is percent-decoded and its hyphens become spaces so it can be compared
    with real episode titles.
    """
    match = APPLE_PODCAST_URL_PATTERN.match((podcast_url or "").strip())
    if not match:
        raise ValueError(
            "Not an Apple Podcasts URL (expected https://podcasts.apple.com/<country>/podcast/<title>/id<number>)"
        )

    slug = unquote(match.group("slug") or "").replace("-", " ").strip()
    return match.group("id"), slug


def extract_real_title(soup):
    """Return the episode title from the page: first <h1>, else og:title, else <title>."""
    h1_tag = soup.find("h1")
    if isinstance(h1_tag, Tag):
        return h1_tag.get_text(strip=True)

    meta_tag = soup.find("meta", property="og:title")
    if isinstance(meta_tag, Tag):
        return str(meta_tag.get("content", "")).strip()

    title_tag = soup.find("title")
    full_title = title_tag.get_text(strip=True) if isinstance(title_tag, Tag) else ""
    return full_title.split(TITLE_SEPARATOR)[0].strip()


def podcast_info(podcast_url):
    """Fetch the podcast ID and episode title (both parsed and real) from an Apple Podcasts URL."""
    podcast_id, episode_title_parsed = parse_podcast_url(podcast_url)
    podcast_url = podcast_url.strip()

    response = requests.get(podcast_url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code != HTTP_OK:
        raise RuntimeError(f"Failed to retrieve the podcast page. Status code: {response.status_code}")

    soup = BeautifulSoup(response.content, "html.parser")
    return podcast_id, episode_title_parsed, extract_real_title(soup)
