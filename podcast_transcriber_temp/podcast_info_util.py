import requests
from bs4 import BeautifulSoup

def podcast_info(podcast_url):
    # Extract the podcast ID from the Apple Podcasts URL
    podcast_id = podcast_url.split('/id')[-1].split('?')[0]
    
    # Extract the parsed episode title from the URL
    episode_title_parsed = podcast_url.split('/podcast/')[-1].split('/id')[0]
    
    # Make a request to the Apple Podcasts page to retrieve the actual episode title
    response = requests.get(podcast_url)
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Try to find the episode title in an <h1> tag
        episode_title_real = soup.find('h1')
        if episode_title_real:
            episode_title_real = episode_title_real.text.strip()
        else:
            # If not found, try to find the title in a <meta> tag with property 'og:title'
            meta_tag = soup.find('meta', property='og:title')
            if meta_tag:
                episode_title_real = meta_tag['content'].strip()
            else:
                # If not found, fall back to the <title> tag and extract the first part
                full_title = soup.find('title').text.strip()
                episode_title_real = full_title.split(" - ")[0].strip()
        
        return podcast_id, episode_title_parsed, episode_title_real
    else:
        raise Exception(f"Failed to retrieve the podcast page. Status code: {response.status_code}")
