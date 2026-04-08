#!/usr/bin/env python3
"""
podcast_info_util.py - Extract podcast ID and episode title from an Apple Podcasts URL.
"""

from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup, Tag

HTTP_OK = 200


def podcast_info(podcast_url):
    """Fetch the podcast ID and episode title (both parsed and real) from an Apple Podcasts URL."""
    podcast_id = podcast_url.split('/id')[-1].split('?')[0]
    episode_title_parsed = unquote(podcast_url.split('/podcast/')[-1].split('/id')[0])

    response = requests.get(podcast_url)

    if response.status_code == HTTP_OK:
        soup = BeautifulSoup(response.content, 'html.parser')

        h1_tag = soup.find('h1')
        if isinstance(h1_tag, Tag):
            episode_title_real = h1_tag.get_text(strip=True)
        else:
            meta_tag = soup.find('meta', property='og:title')
            if isinstance(meta_tag, Tag):
                episode_title_real = str(meta_tag.get('content', '')).strip()
            else:
                title_tag = soup.find('title')
                full_title = title_tag.get_text(strip=True) if isinstance(title_tag, Tag) else ""
                episode_title_real = full_title.split(" - ")[0].strip()

        return podcast_id, episode_title_parsed, episode_title_real
    else:
        raise Exception(f"Failed to retrieve the podcast page. Status code: {response.status_code}")
