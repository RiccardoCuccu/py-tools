#!/usr/bin/env python3
"""
episode_link_util.py - Resolve an Apple Podcasts episode URL to a direct audio enclosure link.
"""

import difflib

import feedparser
import requests

HTTP_OK = 200
SIMILARITY_THRESHOLD = 0.6
REQUEST_TIMEOUT_SECONDS = 30
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
AUDIO_MIME_PREFIX = "audio/"


def fetch_feed_url(podcast_id):
    """Ask the iTunes lookup API for the RSS feed URL of podcast_id."""
    response = requests.get(
        ITUNES_LOOKUP_URL, params={"id": podcast_id}, timeout=REQUEST_TIMEOUT_SECONDS
    )

    if response.status_code != HTTP_OK:
        raise RuntimeError(f"Error fetching podcast details: {response.status_code}")

    results = response.json().get("results") or []
    if not results:
        raise LookupError("Podcast not found.")

    rss_feed_url = results[0].get("feedUrl")
    if not rss_feed_url:
        raise LookupError("RSS feed URL not found in the podcast details.")

    return rss_feed_url


def find_best_entry(entries, *titles):
    """Return (entry, ratio) for the feed entry whose title is most similar to any of titles."""
    best_match = None
    best_ratio = 0.0
    wanted = [t.lower() for t in titles if t]

    for entry in entries:
        entry_title = (entry.get("title") or "").lower()
        if not entry_title:
            continue

        for title in wanted:
            ratio = difflib.SequenceMatcher(None, title, entry_title).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = entry

    return best_match, best_ratio


def entry_audio_url(entry):
    """Return the audio URL of a feed entry: audio enclosure, any enclosure, else the entry link."""
    enclosures = [e for e in (entry.get("enclosures") or []) if e.get("href")]

    for enclosure in enclosures:
        if str(enclosure.get("type", "")).startswith(AUDIO_MIME_PREFIX):
            return enclosure["href"]

    if enclosures:
        return enclosures[0]["href"]

    return entry.get("link")


def episode_link(podcast_id, episode_title_parsed, episode_title_real):
    """Look up the RSS feed for podcast_id and return the best-matching episode audio URL."""
    rss_feed_url = fetch_feed_url(podcast_id)

    # Fetch with requests so the download has a timeout (feedparser's own fetch has none)
    feed_response = requests.get(rss_feed_url, timeout=REQUEST_TIMEOUT_SECONDS)
    if feed_response.status_code != HTTP_OK:
        raise RuntimeError(f"Error fetching the RSS feed: {feed_response.status_code}")
    feed = feedparser.parse(feed_response.content)

    best_match, best_ratio = find_best_entry(
        feed.entries, episode_title_parsed, episode_title_real
    )

    if best_match is None or best_ratio <= SIMILARITY_THRESHOLD:
        raise LookupError("Episode not found in the RSS feed.")

    audio_url = entry_audio_url(best_match)
    if not audio_url:
        raise LookupError("The matching episode has no audio link.")

    return audio_url
