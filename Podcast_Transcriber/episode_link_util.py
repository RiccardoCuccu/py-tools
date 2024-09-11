import requests
import feedparser
import difflib

def episode_link(podcast_id, episode_title_parsed, episode_title_real):
    # Use iTunes Search API to get podcast details
    url = f"https://itunes.apple.com/lookup?id={podcast_id}"
    response = requests.get(url)
    
    if response.status_code != 200:
        raise Exception(f"Error fetching podcast details: {response.status_code}")
    
    data = response.json()

    # Extract RSS feed URL from the response
    if data['resultCount'] > 0:
        rss_feed_url = data['results'][0].get('feedUrl', None)
        
        if rss_feed_url:
            # Parse the RSS feed
            feed = feedparser.parse(rss_feed_url)
            
            best_match = None
            best_ratio = 0.0

            # Try to find the episode using either episode_title_parsed or episode_title_real
            for entry in feed.entries:
                entry_title = entry.title.lower()
                episode_title_parsed_lower = episode_title_parsed.lower()
                episode_title_real_lower = episode_title_real.lower()
                
                # Compare the episode title with parsed and real titles using difflib
                ratio_parsed = difflib.SequenceMatcher(None, episode_title_parsed_lower, entry_title).ratio()
                ratio_real = difflib.SequenceMatcher(None, episode_title_real_lower, entry_title).ratio()

                # Keep track of the best match
                if ratio_parsed > best_ratio:
                    best_ratio = ratio_parsed
                    best_match = entry
                if ratio_real > best_ratio:
                    best_ratio = ratio_real
                    best_match = entry
                
            # If a good enough match is found, return the enclosure link if available
            if best_match and best_ratio > 0.6:  # 60% similarity threshold
                if 'enclosures' in best_match and len(best_match.enclosures) > 0:
                    # Return the direct link to the audio file in the enclosure
                    return best_match.enclosures[0].href
                elif hasattr(best_match, 'link'):
                    return best_match.link
            else:
                raise Exception("Episode not found in the RSS feed.")
        else:
            raise Exception("RSS feed URL not found in the podcast details.")
    else:
        raise Exception("Podcast not found.")
