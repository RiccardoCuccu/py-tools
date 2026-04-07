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
import html
import re
import sys
from xml.etree import ElementTree as ET

import requests

# HTTP status codes
HTTP_OK = 200

# Network settings
FETCH_TIMEOUT_SECONDS = 10


def strip_html(text):
    """Remove HTML tags and decode HTML entities, converting <br> to newlines."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def extract_encoded_parts_from_url(url_google):
    """Extract Base64-encoded feed URL and episode ID from a Google Podcasts URL."""
    pattern = r'podcasts\.google\.com/feed/([^/]+)/episode/([^?]+)'
    match = re.search(pattern, url_google)

    if not match:
        raise ValueError("Invalid Google Podcasts URL format")

    feed_encoded = match.group(1)
    episode_id_encoded = match.group(2)

    return feed_encoded, episode_id_encoded


def decode_google_podcasts_url(url_google):
    """Decode the Google Podcasts URL to extract the feed URL and episode ID."""
    feed_encoded, episode_id_encoded = extract_encoded_parts_from_url(url_google)

    try:
        feed_url = base64.b64decode(feed_encoded + "=" * (-len(feed_encoded) % 4)).decode("utf-8")
        episode_id = base64.b64decode(episode_id_encoded + "=" * (-len(episode_id_encoded) % 4)).decode("utf-8")
    except Exception as e:
        raise ValueError(f"Error decoding Base64: {e}")

    return feed_url, episode_id


def fetch_rss_feed(feed_url):
    """Retrieve the RSS feed content from the podcast host."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(feed_url, headers=headers, timeout=FETCH_TIMEOUT_SECONDS)

        if response.status_code == HTTP_OK:
            return response.content
        else:
            print(f"HTTP Error: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error while fetching feed: {e}")
        return None


def find_episode_in_feed(feed_content, episode_id):
    """Search for the specific episode in the RSS feed and return its metadata dict."""
    if not feed_content:
        return None

    try:
        root = ET.fromstring(feed_content)

        channel = root.find("channel")
        show_info = {}

        if channel is not None:
            title_el = channel.find("title")
            desc_el = channel.find("description")
            show_info["show_title"] = title_el.text if title_el is not None else "N/A"
            show_info["show_description"] = desc_el.text if desc_el is not None else "N/A"

        items = root.findall(".//item")

        for item in items:
            guid = item.find("guid")

            if guid is not None and guid.text and episode_id in guid.text:
                title_el = item.find("title")
                desc_el = item.find("description")
                pub_el = item.find("pubDate")
                link_el = item.find("link")
                episode = {
                    "title": title_el.text if title_el is not None else "N/A",
                    "description": desc_el.text if desc_el is not None else "N/A",
                    "publication_date": pub_el.text if pub_el is not None else "N/A",
                    "link": link_el.text if link_el is not None else "N/A",
                    "guid": guid.text,
                    "show_info": show_info,
                }

                enclosure = item.find("enclosure")
                if enclosure is not None:
                    episode["audio_url"] = enclosure.get("url")

                return episode

        return None

    except Exception as e:
        print(f"Error while parsing XML: {e}")
        return None


def get_google_podcast_url():
    """Prompt the user to input a Google Podcasts URL and return it."""
    print("\n" + "=" * 60)
    print("GOOGLE PODCASTS URL INPUT")
    print("=" * 60)
    print("\nPlease paste the full Google Podcasts URL:")
    print("(Example: https://podcasts.google.com/feed/.../episode/...)\n")

    url = input("URL: ").strip()

    if not url:
        raise ValueError("No URL provided")

    return url


def display_episode_info(episode):
    """Print all retrieved episode and show information to stdout."""
    print("\nEPISODE FOUND!\n")
    print("=" * 60)
    print("SHOW INFORMATION")
    print("=" * 60)
    print(f"Title: {episode['show_info']['show_title']}")
    print(f"Description: {episode['show_info']['show_description']}")

    print("\n" + "=" * 60)
    print("EPISODE INFORMATION")
    print("=" * 60)
    print(f"Title: {episode['title']}")
    print(f"Publication Date: {episode['publication_date']}")
    print(f"Link: {episode['link']}")

    if episode.get("audio_url"):
        print(f"Audio URL: {episode['audio_url']}")

    print(f"\nDescription:")
    print(strip_html(episode["description"]))


def _parse_args():
    """Parse optional command-line URL argument."""
    parser = argparse.ArgumentParser(
        description="Decode a Google Podcasts URL and retrieve episode details."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Google Podcasts episode URL (prompted interactively if omitted).",
    )
    return parser.parse_args()


def main():
    """Orchestrate URL decoding, RSS fetch, and episode display."""
    args = _parse_args()

    try:
        google_podcast_url = args.url if args.url else get_google_podcast_url()

        print(f"\nProcessing URL: {google_podcast_url}")

        feed_url, episode_id = decode_google_podcasts_url(google_podcast_url)

        print(f"\nFeed URL: {feed_url}")
        print(f"Episode ID: {episode_id}")

        print("\n" + "=" * 60)
        print("ATTEMPTING TO FETCH RSS FEED...")
        print("=" * 60)

        feed_content = fetch_rss_feed(feed_url)

        if feed_content:
            episode = find_episode_in_feed(feed_content, episode_id)

            if episode:
                display_episode_info(episode)
            else:
                print("\nEpisode NOT found in RSS feed")
                print("Possible causes:")
                print("- The episode was removed")
                print("- The feed no longer includes this episode")
                print("- The episode ID does not match")
        else:
            print("\nUnable to fetch the RSS feed")
            print("\nPossible alternative solutions:")
            print("1. Contact the podcast author directly")
            print("2. Search on archive.org (Wayback Machine)")
            print("3. Check for backups or mirrors of the feed")

    except ValueError as e:
        print(f"\nError: {e}")
        print("\nPlease provide a valid Google Podcasts URL")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
