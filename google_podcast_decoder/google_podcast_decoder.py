"""
Google Podcasts URL Decoder

This script decodes Google Podcasts URLs to extract podcast episode information
from RSS feeds. It supports both interactive mode and command-line arguments.

USAGE:
    1. Command-line argument:
       python google_podcast_decoder.py "https://podcasts.google.com/feed/BASE64_FEED/episode/BASE64_EPISODE"
    
    2. Interactive mode (no arguments):
       python google_podcast_decoder.py
       Then paste the URL when prompted

GOOGLE PODCASTS URL FORMAT:
    https://podcasts.google.com/feed/{BASE64_ENCODED_FEED_URL}/episode/{BASE64_ENCODED_EPISODE_ID}
    
    Where:
    - BASE64_ENCODED_FEED_URL: The RSS feed URL encoded in Base64
    - BASE64_ENCODED_EPISODE_ID: The unique episode identifier encoded in Base64

EXAMPLE:
    python google_podcast_decoder.py "https://podcasts.google.com/feed/aHR0cHM6Ly93d3cuc3ByZWFrZXIuY29tL3Nob3cvMjIwNTc0Mi9lcGlzb2Rlcy9mZWVk/episode/YTNlNjI2YjQtNjg2Zi00ZmFjLTgzZDEtYWJiMmM4NDdjMDM0"

OUTPUT:
    - Show information (title, description)
    - Episode details (title, publication date, description, audio URL)
    - Direct links to the episode

REQUIREMENTS:
    - requests library: pip install requests
"""

import requests
import base64
import sys
import re
from xml.etree import ElementTree as ET

def extract_encoded_parts_from_url(url_google):
    """Extracts Base64-encoded feed URL and episode ID from Google Podcasts URL"""
    pattern = r'podcasts\.google\.com/feed/([^/]+)/episode/([^?]+)'
    match = re.search(pattern, url_google)
    
    if not match:
        raise ValueError("Invalid Google Podcasts URL format")
    
    feed_encoded = match.group(1)
    episode_id_encoded = match.group(2)
    
    return feed_encoded, episode_id_encoded

def decode_google_podcasts_url(url_google):
    """Decodes the Google Podcasts URL to extract the feed URL and episode ID"""
    feed_encoded, episode_id_encoded = extract_encoded_parts_from_url(url_google)
    
    try:
        feed_url = base64.b64decode(feed_encoded).decode('utf-8')
        episode_id = base64.b64decode(episode_id_encoded).decode('utf-8')
    except Exception as e:
        raise ValueError(f"Error decoding Base64: {e}")
    
    return feed_url, episode_id

def fetch_rss_feed(feed_url):
    """Retrieves the RSS feed content from the podcast host"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(feed_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return response.content
        else:
            print(f"HTTP Error: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error while fetching feed: {e}")
        return None

def find_episode_in_feed(feed_content, episode_id):
    """Searches for the specific episode in the RSS feed"""
    if not feed_content:
        return None
    
    try:
        root = ET.fromstring(feed_content)
        
        channel = root.find('channel')
        show_info = {}
        
        if channel is not None:
            show_info['show_title'] = channel.find('title').text if channel.find('title') is not None else "N/A"
            show_info['show_description'] = channel.find('description').text if channel.find('description') is not None else "N/A"
        
        items = root.findall('.//item')
        
        for item in items:
            guid = item.find('guid')
            
            if guid is not None and episode_id in guid.text:
                episode = {
                    'title': item.find('title').text if item.find('title') is not None else "N/A",
                    'description': item.find('description').text if item.find('description') is not None else "N/A",
                    'publication_date': item.find('pubDate').text if item.find('pubDate') is not None else "N/A",
                    'link': item.find('link').text if item.find('link') is not None else "N/A",
                    'guid': guid.text,
                    'show_info': show_info
                }
                
                enclosure = item.find('enclosure')
                if enclosure is not None:
                    episode['audio_url'] = enclosure.get('url')
                
                return episode
        
        return None
        
    except Exception as e:
        print(f"Error while parsing XML: {e}")
        return None

def get_google_podcast_url():
    """Prompts the user to input a Google Podcasts URL"""
    print("\n" + "=" * 60)
    print("GOOGLE PODCASTS URL INPUT")
    print("=" * 60)
    print("\nPlease paste the full Google Podcasts URL:")
    print("(Example: https://podcasts.google.com/feed/.../episode/...)\n")
    
    url = input("URL: ").strip()
    
    if not url:
        raise ValueError("No URL provided")
    
    return url

def display_episode_info(episode, feed_url, episode_id):
    """Displays the retrieved episode information"""
    print("\n✓ EPISODE FOUND!\n")
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
    
    if episode.get('audio_url'):
        print(f"Audio URL: {episode['audio_url']}")
    
    print(f"\nDescription:")
    print(episode['description'])

def main():
    """Main function that orchestrates the podcast episode retrieval process"""
    try:
        if len(sys.argv) > 1:
            google_podcast_url = sys.argv[1]
            print(f"\nUsing URL from command-line argument")
        else:
            google_podcast_url = get_google_podcast_url()
        
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
                display_episode_info(episode, feed_url, episode_id)
            else:
                print("\n✗ Episode NOT found in RSS feed")
                print("Possible causes:")
                print("- The episode was removed")
                print("- The feed no longer includes this episode")
                print("- The episode ID does not match")
        else:
            print("\n✗ Unable to fetch the RSS feed")
            print("\nPossible alternative solutions:")
            print("1. Contact the podcast author directly")
            print("2. Search on archive.org (Wayback Machine)")
            print("3. Check for backups or mirrors of the feed")
    
    except ValueError as e:
        print(f"\n✗ Error: {e}")
        print("\nPlease provide a valid Google Podcasts URL")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()