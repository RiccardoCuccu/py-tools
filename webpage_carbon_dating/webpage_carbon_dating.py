#!/usr/bin/env python3
"""
Webpage Carbon Dating - Attempt to find the original publication date of a webpage from its metadata.

Checks common meta tags (article:published_time, og:published_time, DC.date.issued, etc.)
and the <time> element for a date value.

Usage:
    python webpage_carbon_dating.py

Notes:
    - A URL without a scheme (e.g. example.com/post) is treated as https.
"""

import re
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

# HTTP status codes
HTTP_OK = 200

# Network settings
REQUEST_TIMEOUT_SECONDS = 15
DEFAULT_URL_SCHEME = "https://"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Meta tag attributes to search for publication date information
POSSIBLE_DATE_TAGS = [
    {"property": "article:published_time"},
    {"name": "date"},
    {"name": "pubdate"},
    {"name": "article:published_time"},
    {"name": "DC.date.issued"},
    {"itemprop": "datePublished"},
    {"property": "og:published_time"},
]

# Leading ISO calendar date, e.g. 2021-03-05 in "2021-03-05T10:00:00Z"
ISO_DATE_PREFIX = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})")


def normalize_date(raw_value: str) -> str:
    """
    Reduce a metadata date value to YYYY-MM-DD when it starts with an ISO date.

    Handles both "T" and space separators between date and time. Values in any
    other format are returned stripped but otherwise unchanged.
    """
    match = ISO_DATE_PREFIX.match(raw_value)
    if match:
        return match.group(1)
    return raw_value.strip()


def normalize_url(url: str) -> str:
    """Return url stripped, with https:// prepended when no scheme is present."""
    url = url.strip()
    if url and "://" not in url:
        return DEFAULT_URL_SCHEME + url
    return url


def extract_publication_date(html: bytes | str) -> Optional[str]:
    """
    Search HTML metadata for a publication date.

    Returns the date string (YYYY-MM-DD when ISO formatted) or None if no
    non-empty date value is present in the known meta tags or <time> element.
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in POSSIBLE_DATE_TAGS:
        for meta_tag in soup.find_all("meta", attrs=tag):  # type: ignore[arg-type]
            if not isinstance(meta_tag, Tag):
                continue
            content = str(meta_tag.get("content") or "").strip()
            if content:
                return normalize_date(content)

    for time_tag in soup.find_all("time"):
        if not isinstance(time_tag, Tag):
            continue
        datetime_val = str(time_tag.get("datetime") or "").strip()
        if datetime_val:
            return normalize_date(datetime_val)

    return None


def get_publication_date_from_html(url):
    """
    Fetch url and search its metadata for a publication date.

    Returns a human-readable string with the date if found, or a message
    indicating that no date was present in the page metadata or that the page
    could not be loaded.
    """
    url = normalize_url(url)
    if not url:
        return "Error: no URL provided."

    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return f"Error loading the page: {exc}"

    if response.status_code != HTTP_OK:
        return f"Error loading the page: {response.status_code}"

    publication_date = extract_publication_date(response.content)
    if publication_date:
        return f"Publication date found: {publication_date}"

    return "Publication date not found in the metadata."


if __name__ == "__main__":
    url = input("Enter the URL of the site: ")
    print(get_publication_date_from_html(url))
