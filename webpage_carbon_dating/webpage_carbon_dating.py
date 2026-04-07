#!/usr/bin/env python3
"""
Webpage Carbon Dating - Attempt to find the original publication date of a webpage from its metadata.

Checks common meta tags (article:published_time, og:published_time, DC.date.issued, etc.)
and the <time> element for a date value.

Usage:
    python webpage_carbon_dating.py
"""

import requests
from bs4 import BeautifulSoup, Tag

# HTTP status codes
HTTP_OK = 200

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


def get_publication_date_from_html(url):
    """
    Fetch url and search its metadata for a publication date.

    Returns a human-readable string with the date if found, or a message
    indicating that no date was present in the page metadata.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=15)

    if response.status_code != HTTP_OK:
        return f"Error loading the page: {response.status_code}"

    soup = BeautifulSoup(response.content, "html.parser")

    for tag in POSSIBLE_DATE_TAGS:
        meta_tag = soup.find("meta", attrs=tag)  # type: ignore[arg-type]
        if isinstance(meta_tag, Tag):
            content = meta_tag.get("content")
            if content:
                publication_date = str(content).split("T")[0]
                return f"Publication date found: {publication_date}"

    time_tag = soup.find("time")
    if isinstance(time_tag, Tag):
        datetime_val = time_tag.get("datetime")
        if datetime_val:
            publication_date = str(datetime_val).split("T")[0]
            return f"Publication date found: {publication_date}"

    return "Publication date not found in the metadata."


if __name__ == "__main__":
    url = input("Enter the URL of the site: ")
    print(get_publication_date_from_html(url))
