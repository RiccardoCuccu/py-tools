import requests
from bs4 import BeautifulSoup

def get_publication_date_from_html(url):
    # Perform the HTTP request to get the content of the page
    response = requests.get(url)
    
    if response.status_code != 200:
        return f"Error loading the page: {response.status_code}"
    
    # Parse the HTML content of the page
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Possible tags that might contain the publication date
    possible_date_tags = [
        {'property': 'article:published_time'},
        {'name': 'date'},
        {'name': 'pubdate'},
        {'name': 'article:published_time'},
        {'name': 'DC.date.issued'},
        {'itemprop': 'datePublished'},
        {'property': 'og:published_time'},
    ]
    
    # Search for the date in the meta tags
    for tag in possible_date_tags:
        meta_tag = soup.find('meta', tag)
        if meta_tag and meta_tag.get('content'):
            # Split the date to remove the time if it exists
            publication_date = meta_tag['content'].split("T")[0]
            return f"Publication date found: {publication_date}"
    
    # Also search the <time> tag if it exists
    time_tag = soup.find('time')
    if time_tag and time_tag.get('datetime'):
        # Split the date to remove the time if it exists
        publication_date = time_tag['datetime'].split("T")[0]
        return f"Publication date found: {publication_date}"
    
    return "Publication date not found in the metadata."

# Example of usage
url = input("Enter the URL of the site: ")
date = get_publication_date_from_html(url)
print(date)
