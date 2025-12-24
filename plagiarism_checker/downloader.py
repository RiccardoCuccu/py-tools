"""
Content Downloader Module - STEP 4

Downloads and caches content from URLs with multi-method retry strategy.
Supports compressed caching to reduce disk usage.
Includes API-based fallbacks for academic sources.
"""

import sys
import time
import hashlib
import re
import gzip
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
    from bs4 import BeautifulSoup
    from nltk.tokenize import sent_tokenize
except ImportError as e:
    print(f"Error: Missing required library - {e}")
    print("pip install requests beautifulsoup4 nltk")
    sys.exit(1)


class ContentDownloader:
    def __init__(self, doc_path, cache_only=False):
        """Initialize content downloader with cache directory"""
        self.doc_path = Path(doc_path)
        script_dir = Path(__file__).resolve().parent
        self.cache_dir = script_dir / ".plagiarism_cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_only = cache_only

    def get_cached_sources(self, urls):
        """Get only cached sources without downloading new ones"""
        sources = []
        
        for i, url in enumerate(urls, 1):
            url_hash = hashlib.md5(url.encode()).hexdigest()
            cached_content = self._read_cache(url_hash)
            
            if cached_content and len(cached_content) > 200:
                sources.append({
                    'url': url,
                    'content': cached_content,
                    'title': self._extract_title(cached_content)
                })
                print(f"  Loaded from cache {i}/{len(urls)}: {url}")
            else:
                print(f"  Not in cache {i}/{len(urls)}: {url}")
        
        if sources:
            print(f"✓ Loaded {len(sources)} sources from cache")
        
        return sources

    def download_all_sources(self, urls):
        """Download content from all URLs and track failures"""
        print(f"\n[4/5] Downloading content from sources...")
        sources = []
        failed_sources = []

        for i, url in enumerate(urls, 1):
            print(f"  Downloading {i}/{len(urls)}: {url}")
            content, error = self._download_content(url)

            if content and len(content) > 200:
                sources.append({
                    'url': url,
                    'content': content,
                    'title': self._extract_title(content)
                })
            else:
                reason = error if error else "Content too short or corrupted (< 200 readable characters)"
                failed_sources.append({
                    'url': url,
                    'reason': reason
                })
                if not error:
                    print(f"    ✗ Skipped: Content appears corrupted or is a binary file")
                else:
                    print(f"    ✗ Failed: {reason}")

            time.sleep(1)

        print(f"✓ Successfully downloaded {len(sources)} sources")
        if failed_sources:
            print(f"✗ Failed to download {len(failed_sources)} sources")
        return sources, failed_sources

    def _download_content(self, url):
        """Download and extract text content from a URL with multi-method retry strategy"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        
        cached_content = self._read_cache(url_hash)
        if cached_content:
            return cached_content, None

        # Try API-based methods first for academic sources
        if self._is_academic_source(url):
            content, error = self._try_api_methods(url)
            if content:
                self._write_cache(url_hash, content)
                return content, None

        # Fallback to traditional scraping methods
        strategies = [
            (self._method_desktop, 15, 2),
            (self._method_mobile, 25, 5),
            (self._method_session, 35, 10)
        ]
        last_error = None

        for attempt, (method, timeout, delay) in enumerate(strategies):
            try:
                text = method(url, timeout)
                if text and len(text) > 0:
                    self._write_cache(url_hash, text)
                    return text, None
            except requests.exceptions.Timeout:
                last_error = f"Timeout after {timeout}s"
            except requests.exceptions.ConnectionError:
                last_error = "Connection failed"
            except requests.exceptions.RequestException as e:
                last_error = str(e)
            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"
            
            print(f"    Attempt {attempt + 1}/3 failed: {last_error}")

            if attempt < 2:
                time.sleep(delay)

        return None, last_error if last_error else "Unknown error"

    def _is_academic_source(self, url):
        """Check if URL is from an academic source that has API access"""
        academic_domains = [
            'doi.org', 'arxiv.org', 'semanticscholar.org',
            'pubmed', 'ncbi.nlm.nih.gov', 'biorxiv.org',
            'medrxiv.org', 'ssrn.com', 'researchgate.net'
        ]
        parsed = urlparse(url)
        return any(domain in parsed.netloc.lower() for domain in academic_domains)

    def _try_api_methods(self, url):
        """Try API-based methods to fetch academic content"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # arXiv API
        if 'arxiv.org' in domain:
            content = self._fetch_arxiv_api(url)
            if content:
                return content, None

        # DOI resolution via Unpaywall API
        if 'doi.org' in domain or '/doi/' in url.lower():
            content = self._fetch_via_unpaywall(url)
            if content:
                return content, None

        # Semantic Scholar API
        if 'semanticscholar.org' in domain:
            content = self._fetch_semantic_scholar(url)
            if content:
                return content, None

        return None, "No API method available"

    def _fetch_arxiv_api(self, url):
        """Fetch content from arXiv using their API"""
        try:
            # Extract arXiv ID from URL
            arxiv_id = re.search(r'arxiv\.org/abs/(\d+\.\d+)', url)
            if not arxiv_id:
                return None

            arxiv_id = arxiv_id.group(1)
            api_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
            
            response = requests.get(api_url, timeout=15)
            if response.status_code == 200:
                from xml.etree import ElementTree as ET
                root = ET.fromstring(response.content)
                namespace = {'atom': 'http://www.w3.org/2005/Atom'}
                
                entry = root.find('atom:entry', namespace)
                if entry is not None:
                    title = entry.find('atom:title', namespace)
                    summary = entry.find('atom:summary', namespace)
                    
                    content_parts = []
                    if title is not None and title.text:
                        content_parts.append(f"Title: {title.text.strip()}")
                    if summary is not None and summary.text:
                        content_parts.append(f"Abstract: {summary.text.strip()}")
                    
                    if content_parts:
                        print(f"    ✓ Fetched from arXiv API")
                        return "\n\n".join(content_parts)
        except Exception as e:
            print(f"    arXiv API failed: {str(e)}")
        
        return None

    def _fetch_via_unpaywall(self, url):
        """Fetch content via Unpaywall API for DOI links"""
        try:
            # Extract DOI from URL
            doi_match = re.search(r'10\.\d{4,}/[^\s]+', url)
            if not doi_match:
                return None
            
            doi = doi_match.group(0).rstrip('.,;')
            
            # Try Unpaywall API to find open access version
            unpaywall_url = f"https://api.unpaywall.org/v2/{doi}?email=user@example.com"
            response = requests.get(unpaywall_url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check for open access PDF or landing page
                if data.get('is_oa'):
                    best_location = data.get('best_oa_location')
                    if best_location:
                        pdf_url = best_location.get('url_for_pdf')
                        landing_url = best_location.get('url_for_landing_page')
                        
                        # Try PDF first
                        if pdf_url:
                            content = self._download_pdf_as_text(pdf_url)
                            if content:
                                print(f"    ✓ Fetched open access PDF via Unpaywall")
                                return content
                        
                        # Try landing page
                        if landing_url:
                            content = self._method_desktop(landing_url, 15)
                            if content:
                                print(f"    ✓ Fetched via Unpaywall redirect")
                                return content
                
                # Fallback: get title and abstract from metadata
                title = data.get('title', '')
                abstract = data.get('abstract', '')
                if title or abstract:
                    content_parts = []
                    if title:
                        content_parts.append(f"Title: {title}")
                    if abstract:
                        content_parts.append(f"Abstract: {abstract}")
                    if content_parts:
                        print(f"    ✓ Fetched metadata via Unpaywall")
                        return "\n\n".join(content_parts)
        except Exception as e:
            print(f"    Unpaywall API failed: {str(e)}")
        
        return None

    def _fetch_semantic_scholar(self, url):
        """Fetch content from Semantic Scholar"""
        try:
            # Extract paper ID from URL
            paper_id = re.search(r'semanticscholar\.org/paper/([a-f0-9]+)', url)
            if not paper_id:
                return None
            
            paper_id = paper_id.group(1)
            api_url = f"https://api.semanticscholar.org/v1/paper/{paper_id}"
            
            response = requests.get(api_url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                
                title = data.get('title', '')
                abstract = data.get('abstract', '')
                
                content_parts = []
                if title:
                    content_parts.append(f"Title: {title}")
                if abstract:
                    content_parts.append(f"Abstract: {abstract}")
                
                if content_parts:
                    print(f"    ✓ Fetched from Semantic Scholar API")
                    return "\n\n".join(content_parts)
        except Exception as e:
            print(f"    Semantic Scholar API failed: {str(e)}")
        
        return None

    def _download_pdf_as_text(self, url):
        """Download and extract text from PDF URL"""
        try:
            response = requests.get(url, timeout=20, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if response.status_code == 200 and 'application/pdf' in response.headers.get('Content-Type', ''):
                # Try to extract text using PyMuPDF if available
                try:
                    import fitz
                    import io
                    
                    pdf_stream = io.BytesIO(response.content)
                    doc = fitz.open(stream=pdf_stream, filetype="pdf")  # type: ignore[attr-defined]
                    text = ""
                    for page in doc:
                        text += page.get_text()
                    doc.close()
                    
                    if len(text) > 200:
                        return text
                except ImportError:
                    pass
        except Exception:
            pass
        
        return None

    def _read_cache(self, url_hash):
        """Read cached content with support for both compressed and uncompressed formats"""
        cache_file_gz = self.cache_dir / f"{url_hash}.txt.gz"
        try:
            with gzip.open(cache_file_gz, 'rt', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except FileNotFoundError:
            pass
        except Exception:
            pass
        
        cache_file = self.cache_dir / f"{url_hash}.txt"
        try:
            content = cache_file.read_text(encoding='utf-8', errors='ignore')
            try:
                self._write_cache(url_hash, content)
                cache_file.unlink()
            except Exception:
                pass
            return content
        except FileNotFoundError:
            pass
        
        return None

    def _write_cache(self, url_hash, text):
        """Write content to cache with compression for large files"""
        cache_file_gz = self.cache_dir / f"{url_hash}.txt.gz"
        try:
            with gzip.open(cache_file_gz, 'wt', encoding='utf-8', errors='ignore') as f:
                f.write(text)
        except Exception:
            cache_file = self.cache_dir / f"{url_hash}.txt"
            cache_file.write_text(text, encoding='utf-8', errors='ignore')

    def _method_desktop(self, url, timeout):
        """Download method 1: Standard desktop User-Agent with academic headers"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if response.status_code == 200:
            return self._extract_text_from_html(response.content)
        raise requests.exceptions.RequestException(f"HTTP {response.status_code}")

    def _method_mobile(self, url, timeout):
        """Download method 2: Mobile User-Agent"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'DNT': '1'
        }
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if response.status_code == 200:
            return self._extract_text_from_html(response.content)
        raise requests.exceptions.RequestException(f"HTTP {response.status_code}")

    def _method_session(self, url, timeout):
        """Download method 3: Session with cookies, referrer and academic-friendly headers"""
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/',
            'DNT': '1',
            'Connection': 'keep-alive'
        }
        response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if response.status_code == 200:
            return self._extract_text_from_html(response.content)
        raise requests.exceptions.RequestException(f"HTTP {response.status_code}")

    def _extract_text_from_html(self, html_content):
        """Extract and clean text from HTML content"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        for script in soup(['script', 'style', 'nav', 'header', 'footer']):
            script.decompose()
        
        text = re.sub(r'\s+', ' ', soup.get_text(separator=' ')).strip()
        
        if text:
            ascii_count = sum(1 for c in text if 32 <= ord(c) <= 126 or c in '\n\r\t')
            total_count = len(text)
            
            if total_count > 0 and (ascii_count / total_count) < 0.7:
                return ""
        
        return text

    def _extract_title(self, text):
        """Extract a reasonable title from text content"""
        sentences = sent_tokenize(text[:500])
        if sentences:
            title = sentences[0][:100]
            return title if len(title) > 10 else "Untitled Source"
        return "Untitled Source"