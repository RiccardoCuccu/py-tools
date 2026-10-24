#!/usr/bin/env python3
"""
Google Podcasts URL Decoder - Decode a Google Podcasts URL and retrieve episode details via RSS.

Extracts the Base64-encoded feed URL and episode ID from a Google Podcasts link,
fetches the RSS feed, and prints all available episode metadata.

Usage:
    python google_podcast_decoder.py
    python google_podcast_decoder.py "https://podcasts.google.com/feed/.../episode/..."

Notes:
    - Google Podcasts was shut down in 2024; this tool works on archived or cached URLs.
    - Requires an internet connection to fetch the RSS feed.
"""

import argparse
import base64
import binascii
import html
import re
import sys
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

import requests

# HTTP status codes
HTTP_OK = 200

# Network settings
FETCH_TIMEOUT_SECONDS = 10
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
ALLOWED_FEED_SCHEMES = ("http", "https")

# URL parsing
GOOGLE_PODCASTS_PATTERN = r"podcasts\.google\.com/feed/([^/?#]+)/episode/([^/?#]+)"
BASE64_BLOCK_SIZE = 4

# Output formatting
NOT_AVAILABLE = "N/A"
SEPARATOR_WIDTH = 60


def strip_html(text):
    """Remove HTML tags and decode HTML entities, converting <br> to newlines."""
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def extract_encoded_parts_from_url(url_google):
    """Extract Base64-encoded feed URL and episode ID from a Google Podcasts URL."""
    match = re.search(GOOGLE_PODCASTS_PATTERN, url_google)

    if not match:
        raise ValueError("Invalid Google Podcasts URL format")

    return match.group(1), match.group(2)


def decode_base64_text(encoded):
    """Decode a Base64 string (standard or URL-safe alphabet, padding optional) to UTF-8 text."""
    cleaned = unquote(encoded).replace("-", "+").replace("_", "/")
    cleaned += "=" * (-len(cleaned) % BASE64_BLOCK_SIZE)

    try:
        return base64.b64decode(cleaned, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as e:
        raise ValueError(f"Error decoding Base64: {e}") from e


def decode_google_podcasts_url(url_google):
    """Decode the Google Podcasts URL to extract the feed URL and episode ID."""
    feed_encoded, episode_id_encoded = extract_encoded_parts_from_url(url_google)

    feed_url = decode_base64_text(feed_encoded)
    episode_id = decode_base64_text(episode_id_encoded)

    if urlparse(feed_url).scheme not in ALLOWED_FEED_SCHEMES:
        raise ValueError(f"Decoded feed URL is not an http(s) URL: {feed_url!r}")

    return feed_url, episode_id


def fetch_rss_feed(feed_url):
    """Retrieve the RSS feed content from the podcast host."""
    try:
        response = requests.get(feed_url, headers=REQUEST_HEADERS, timeout=FETCH_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        print(f"Error while fetching feed: {e}")
        return None

    if response.status_code != HTTP_OK:
        print(f"HTTP Error: {response.status_code}")
        return None

    return response.content


def _text_or_default(parent, tag):
    """Return the stripped text of a child element, or N/A when absent or empty."""
    element = parent.find(tag)
    if element is None or element.text is None or not element.text.strip():
        return NOT_AVAILABLE
    return element.text.strip()


def _guid_matches(guid_text, episode_id):
    """Return True if the item GUID is the episode ID, or contains a non-empty ID."""
    guid_text = guid_text.strip()
    return guid_text == episode_id or (bool(episode_id) and episode_id in guid_text)


def find_episode_in_feed(feed_content, episode_id):
    """Search for the specific episode in the RSS feed and return its metadata dict."""
    if not feed_content:
        return None

    try:
        root = ET.fromstring(feed_content)
    except ET.ParseError as e:
        print(f"Error while parsing XML: {e}")
        return None

    show_info = {"show_title": NOT_AVAILABLE, "show_description": NOT_AVAILABLE}
    channel = root.find("channel")
    if channel is not None:
        show_info["show_title"] = _text_or_default(channel, "title")
        show_info["show_description"] = _text_or_default(channel, "description")

    # Prefer an exact GUID match so a short ID cannot hit an unrelated longer GUID
    items = [i for i in root.findall(".//item") if (i.findtext("guid") or "").strip()]
    item = next((i for i in items if i.findtext("guid", "").strip() == episode_id), None)
    if item is None:
        item = next((i for i in items if _guid_matches(i.findtext("guid", ""), episode_id)), None)

    if item is None:
        return None

    episode = {
        "title": _text_or_default(item, "title"),
        "description": _text_or_default(item, "description"),
        "publication_date": _text_or_default(item, "pubDate"),
        "link": _text_or_default(item, "link"),
        "guid": item.findtext("guid", default="").strip(),
        "show_info": show_info,
    }

    enclosure = item.find("enclosure")
    if enclosure is not None:
        episode["audio_url"] = enclosure.get("url")

    return episode


def get_google_podcast_url():
    """Prompt the user to input a Google Podcasts URL and return it."""
    print("\n" + "=" * SEPARATOR_WIDTH)
    print("GOOGLE PODCASTS URL INPUT")
    print("=" * SEPARATOR_WIDTH)
    print("\nPlease paste the full Google Podcasts URL:")
    print("(Example: https://podcasts.google.com/feed/.../episode/...)\n")

    try:
        url = input("URL: ").strip()
    except EOFError as e:
        raise ValueError("No URL provided") from e

    if not url:
        raise ValueError("No URL provided")

    return url


def display_episode_info(episode):
    """Print all retrieved episode and show information to stdout."""
    print("\nEPISODE FOUND!\n")
    print("=" * SEPARATOR_WIDTH)
    print("SHOW INFORMATION")
    print("=" * SEPARATOR_WIDTH)
    print(f"Title: {episode['show_info']['show_title']}")
    print(f"Description: {strip_html(episode['show_info']['show_description'])}")

    print("\n" + "=" * SEPARATOR_WIDTH)
    print("EPISODE INFORMATION")
    print("=" * SEPARATOR_WIDTH)
    print(f"Title: {episode['title']}")
    print(f"Publication Date: {episode['publication_date']}")
    print(f"Link: {episode['link']}")

    if episode.get("audio_url"):
        print(f"Audio URL: {episode['audio_url']}")

    print("\nDescription:")
    print(strip_html(episode["description"]))


def _parse_args(argv=None):
    """Parse optional command-line URL argument."""
    parser = argparse.ArgumentParser(
        description="Decode a Google Podcasts URL and retrieve episode details."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Google Podcasts episode URL (prompted interactively if omitted).",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """Orchestrate URL decoding, RSS fetch, and episode display. Return the exit code."""
    args = _parse_args(argv)

    try:
        google_podcast_url = args.url if args.url else get_google_podcast_url()

        print(f"\nProcessing URL: {google_podcast_url}")

        feed_url, episode_id = decode_google_podcasts_url(google_podcast_url)

        print(f"\nFeed URL: {feed_url}")
        print(f"Episode ID: {episode_id}")

        print("\n" + "=" * SEPARATOR_WIDTH)
        print("ATTEMPTING TO FETCH RSS FEED...")
        print("=" * SEPARATOR_WIDTH)

        feed_content = fetch_rss_feed(feed_url)

        if not feed_content:
            print("\nUnable to fetch the RSS feed")
            print("\nPossible alternative solutions:")
            print("1. Contact the podcast author directly")
            print("2. Search on archive.org (Wayback Machine)")
            print("3. Check for backups or mirrors of the feed")
            return 1

        episode = find_episode_in_feed(feed_content, episode_id)

        if not episode:
            print("\nEpisode NOT found in RSS feed")
            print("Possible causes:")
            print("- The episode was removed")
            print("- The feed no longer includes this episode")
            print("- The episode ID does not match")
            return 1

        display_episode_info(episode)
        return 0

    except ValueError as e:
        print(f"\nError: {e}")
        print("\nPlease provide a valid Google Podcasts URL")
        return 1
    except KeyboardInterrupt:
        print("\nAborted.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
