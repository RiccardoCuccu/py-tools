#!/usr/bin/env python3
"""
episode_link_util.py - Resolve an Apple Podcasts episode URL to a direct audio enclosure link.
"""

import difflib

import feedparser
import requests

HTTP_OK = 200
SIMILARITY_THRESHOLD = 0.6


def episode_link(podcast_id, episode_title_parsed, episode_title_real):
    """Look up the RSS feed for podcast_id and return the best-matching episode audio URL."""
    url = f"https://itunes.apple.com/lookup?id={podcast_id}"
    response = requests.get(url)

    if response.status_code != HTTP_OK:
        raise Exception(f"Error fetching podcast details: {response.status_code}")

    data = response.json()

    if data['resultCount'] > 0:
        rss_feed_url = data['results'][0].get('feedUrl', None)

        if rss_feed_url:
            feed = feedparser.parse(rss_feed_url)

            best_match = None
            best_ratio = 0.0

            for entry in feed.entries:
                entry_title = entry.title.lower()  # type: ignore[union-attr]
                episode_title_parsed_lower = episode_title_parsed.lower()
                episode_title_real_lower = episode_title_real.lower()

                ratio_parsed = difflib.SequenceMatcher(None, episode_title_parsed_lower, entry_title).ratio()
                ratio_real = difflib.SequenceMatcher(None, episode_title_real_lower, entry_title).ratio()

                if ratio_parsed > best_ratio:
                    best_ratio = ratio_parsed
                    best_match = entry
                if ratio_real > best_ratio:
                    best_ratio = ratio_real
                    best_match = entry

            if best_match and best_ratio > SIMILARITY_THRESHOLD:
                if 'enclosures' in best_match and len(best_match.enclosures) > 0:
                    return best_match.enclosures[0].href
                elif hasattr(best_match, 'link'):
                    return best_match.link
            else:
                raise Exception("Episode not found in the RSS feed.")
        else:
            raise Exception("RSS feed URL not found in the podcast details.")
    else:
        raise Exception("Podcast not found.")
