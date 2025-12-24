"""
Search Engines Module - STEP 3

Handles online searches via DuckDuckGo, SerpApi, and academic APIs. Also manages local reference files.
"""

import sys
import os
import time
import re
from pathlib import Path
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Error: Missing required library - {e}")
    print("pip install requests beautifulsoup4")
    sys.exit(1)

from extractors import TextExtractor


class SearchEngineManager:
    def __init__(self, search_engine, use_apis, use_local, doc_path):
        """Initialize search engine manager with configuration"""
        self.search_engine = search_engine
        self.use_apis = use_apis
        self.use_local = use_local
        self.doc_path = Path(doc_path)
        self.session = requests.Session()
        self.duckduckgo_failed = False
        
        # Get the absolute path of the directory containing this file
        self.script_dir = Path(__file__).resolve().parent
        
        # Load SerpApi key
        self.serpapi_key = self._load_serpapi_key()
        
        # Academic API domains to exclude from web search
        self.api_domains = [
            'arxiv.org', 'semanticscholar.org', 'crossref.org',
            'doi.org', 'ncbi.nlm.nih.gov', 'pubmed'
        ]
        
        # Local references
        self.local_references_dir = self.doc_path.parent / "local_references"
        self.local_sources = []
        self.extractor = TextExtractor(doc_path)

    def _load_serpapi_key(self):
        """Load SerpApi key from config file in script directory"""
        config_path = self.script_dir / ".serpapi_config"
        
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    api_key = f.read().strip()
                    if api_key:
                        print(f"✓ Using SerpApi key from {config_path}")
                        return api_key
                    else:
                        print(f"Warning: .serpapi_config file is empty")
            except Exception as e:
                print(f"Warning: Could not read config file {config_path}: {e}")
        
        # If no key found in file and serpapi is explicitly chosen, prompt user
        if self.search_engine == 'serpapi':
            print("\n" + "=" * 80)
            print("SERPAPI KEY REQUIRED")
            print("=" * 80)
            print("\nNo SerpApi key found in .serpapi_config file.")
            print("SerpApi is the recommended replacement for reliable search results.")
            print("\nTo get a free API key (250 free searches/month):")
            print("  1. Visit https://serpapi.com/")
            print("  2. Sign up for a free account")
            print("  3. Copy your API key from the dashboard")
            print("\nSee SETUP.md for detailed instructions.")
            print("=" * 80)
        
            from main import confirm_continue
            if confirm_continue("\nDo you have a SerpApi key to configure now?"):
                api_key = input("\nEnter your SerpApi key: ").strip()
                if api_key:
                    save_path = self.script_dir / ".serpapi_config"
                    
                    try:
                        with open(save_path, 'w') as f:
                            f.write(api_key)
                        print(f"\n✓ API key saved to {save_path}")
                        
                        # Add to .gitignore if not already present
                        gitignore_path = self.script_dir / ".gitignore"
                        try:
                            gitignore_content = ""
                            if gitignore_path.exists():
                                with open(gitignore_path, 'r') as f:
                                    gitignore_content = f.read()
                            
                            if '.serpapi_config' not in gitignore_content:
                                with open(gitignore_path, 'a') as f:
                                    if gitignore_content and not gitignore_content.endswith('\n'):
                                        f.write('\n')
                                    f.write('\n# SerpApi configuration\n.serpapi_config\n')
                                print(f"✓ Added .serpapi_config to .gitignore")
                            else:
                                print(f"✓ .serpapi_config already in .gitignore")
                        except Exception as e:
                            print(f"⚠ Warning: Could not update .gitignore: {e}")
                            print("  Please manually add .serpapi_config to your .gitignore file")
                        
                        return api_key
                    except Exception as e:
                        print(f"✗ Error: Could not save API key: {e}")
                        print("  API key will be used for this session only.")
                        return api_key
                else:
                    print("\n✗ Error: API key cannot be empty.")
                    print("  Cannot proceed without API key when using --search-engine serpapi")
                    sys.exit(1)
            else:
                print("\nCannot proceed without API key when using --search-engine serpapi")
                sys.exit(1)
        
        return None

    def search_and_load(self, phrases, max_sources):
        """Search online and load local sources, returning combined list of URLs"""
        if self.use_local:
            self._load_local_sources()
        
        urls = self._search_all_phrases(phrases, max_sources)
        
        return urls, []

    def _load_local_sources(self):
        """Load and process local reference files"""
        print(f"\n[3b/5] Loading local reference files...")

        if not self.local_references_dir.exists():
            print(f"  ⚠ Warning: Local references directory not found: {self.local_references_dir}")
            from main import confirm_continue
            if not confirm_continue("  Continue with only online sources?"):
                sys.exit(0)
            return

        local_files = []
        for ext in ['.docx', '.pdf', '.txt']:
            local_files.extend(self.local_references_dir.rglob(f'*{ext}'))

        if not local_files:
            print(f"  ⚠ Warning: No reference files found in {self.local_references_dir}")
            from main import confirm_continue
            if not confirm_continue("  Continue with only online sources?"):
                sys.exit(0)
            return

        print(f"  Found {len(local_files)} local reference file(s)")

        for i, file_path in enumerate(local_files, 1):
            print(f"  Loading {i}/{len(local_files)}: {file_path.name}...")
            text = self.extractor.extract_from_file(file_path)

            if text and len(text) > 200:
                self.local_sources.append({
                    'file_path': str(file_path),
                    'file_name': file_path.name,
                    'content': text,
                    'is_local': True
                })
            else:
                print(f"    Warning: Skipped (content too short or failed to read)")

        print(f"✓ Successfully loaded {len(self.local_sources)} local reference file(s)")

    def _should_include_url(self, url):
        """Check if URL should be included based on exclusion rules"""
        excluded = ['youtube.com', 'facebook.com', 'twitter.com', 'instagram.com']
        if self.use_apis:
            excluded.extend(self.api_domains)
        return not any(x in url.lower() for x in excluded)

    def _search_all_phrases(self, phrases, max_sources):
        """Search for all key phrases and collect unique URLs"""
        if self.use_apis:
            print(f"\n[3/5] Searching academic APIs and online sources...")
        else:
            if self.search_engine == 'serpapi':
                engine_name = "SerpApi"
            elif self.search_engine == 'duckduckgo':
                engine_name = "DuckDuckGo"
                print(f"\n⚠️ WARNING: DuckDuckGo has aggressive rate limiting")
                print(f"  You will likely be blocked after 3-5 searches")
                print(f"  Consider using SerpApi instead (250 free searches/month)")
                print(f"  Set up .serpapi_config or use --search-engine serpapi\n")
            else:  # auto
                if self.serpapi_key:
                    engine_name = "SerpApi"
                else:
                    engine_name = "DuckDuckGo (unreliable - consider using SerpApi)"
                    print(f"\n⚠️ No SerpApi key detected - falling back to DuckDuckGo")
                    print(f"  DuckDuckGo has aggressive rate limiting and will likely fail")
                    print(f"  Get free SerpApi key (250 searches/month): https://serpapi.com/")
                    print(f"  Create .serpapi_config file in script directory for reliable results\n")
            
            print(f"[3/5] Searching online for similar content using {engine_name}...")

        all_urls = set()
        api_count = 0
        web_count = 0
        failed_searches = 0
        total_searches = 0
        consecutive_failures = 0

        for i, phrase in enumerate(phrases, 1):
            print(f"  Searching phrase {i}/{len(phrases)}: \"{phrase[:100]}...\"")

            api_urls = []
            if self.use_apis:
                api_urls = self._search_academic_apis(phrase)
                all_urls.update(api_urls)
                api_count += len(api_urls)

            web_urls = self._search_online(phrase, attempt=i)
            all_urls.update(web_urls)
            web_count += len(web_urls)
            total_searches += 1
            
            if not web_urls and not (self.use_apis and api_urls):
                failed_searches += 1
                consecutive_failures += 1
            else:
                consecutive_failures = 0

            if consecutive_failures >= 3 and not self.serpapi_key and i < len(phrases):
                print(f"\n  ⚠ CRITICAL: {consecutive_failures} consecutive search failures")
                print(f"  DuckDuckGo has blocked your IP address")
                print(f"\n  This tool requires a reliable search API to function properly.")
                print(f"  DuckDuckGo's rate limiting makes it unsuitable for this use case.")
                print(f"\n  SOLUTION: Get a free SerpApi key (250 searches/month):")
                print(f"    1. Visit https://serpapi.com/")
                print(f"    2. Sign up (no credit card required)")
                print(f"    3. Create .serpapi_config file in script directory")
                print(f"\n  Alternative: Use --use-local to compare with local files only")
                
                from main import confirm_continue
                if not confirm_continue(f"\n  Continue searching (will likely fail)?"):
                    print(f"\n  Stopping search. Found {len(all_urls)} sources from {i} searches.")
                    return list(all_urls)[:max_sources]
                consecutive_failures = 0

            if i < len(phrases):
                time.sleep(4)

        unique_urls = list(all_urls)[:max_sources]

        if self.use_apis:
            total_found = api_count + web_count
            num_unique = len(all_urls)
            num_duplicates = total_found - num_unique
            
            if num_unique > max_sources:
                # We found more sources than max_sources, so we limited the results
                print(f"\n✓ Found {len(unique_urls)} unique sources ({api_count} from APIs, {web_count} from web = {total_found} total, kept top {max_sources})")
            elif num_duplicates > 0:
                # We found duplicates
                print(f"\n✓ Found {len(unique_urls)} unique sources ({api_count} from APIs, {web_count} from web = {total_found} total, {num_duplicates} duplicates removed)")
            else:
                # No duplicates, no limiting
                print(f"\n✓ Found {len(unique_urls)} unique sources ({api_count} from APIs, {web_count} from web)")
        else:
            print(f"\n✓ Found {len(unique_urls)} unique sources from {total_searches} searches")
        
        if failed_searches > 0 and total_searches > 0:
            failure_rate = (failed_searches / total_searches) * 100
            print(f"  Note: {failed_searches}/{total_searches} searches returned no results ({failure_rate:.0f}% failure rate)")
            if failure_rate > 50 and not self.serpapi_key:
                print(f"\n  ⚠️ HIGH FAILURE RATE - DuckDuckGo is blocking requests")
                print(f"  RECOMMENDATION: Set up SerpApi for reliable results")
                print(f"  Free tier: 250 searches/month at https://serpapi.com/")

        return unique_urls

    def _search_academic_apis(self, query):
        """Search academic APIs concurrently (CrossRef, arXiv)"""
        all_urls = []
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(self._search_crossref, query): 'crossref',
                executor.submit(self._search_arxiv, query): 'arxiv'
            }
            
            for future in as_completed(futures):
                try:
                    urls = future.result()
                    all_urls.extend(urls)
                except Exception:
                    pass
        
        return list(set(all_urls))

    def _search_crossref(self, query):
        """Search CrossRef API for academic papers"""
        try:
            query_encoded = quote_plus(query[:100])
            url = f"https://api.crossref.org/works?query={query_encoded}&rows=3&mailto=user@example.com"
            response = requests.get(url, headers={'User-Agent': 'PlagiarismChecker/1.0'}, timeout=10)
            if response.status_code == 200:
                urls = []
                for item in response.json().get('message', {}).get('items', []):
                    if doi := item.get('DOI'):
                        urls.append(f"https://doi.org/{doi}")
                return urls
        except (requests.exceptions.RequestException, ValueError, KeyError):
            pass
        return []

    def _search_arxiv(self, query):
        """Search arXiv API for academic papers"""
        from xml.etree import ElementTree as ET
        
        try:
            query_encoded = quote_plus(query[:100])
            url = f"http://export.arxiv.org/api/query?search_query=all:{query_encoded}&start=0&max_results=3"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                namespace = {'atom': 'http://www.w3.org/2005/Atom'}
                urls = []
                for entry in root.findall('atom:entry', namespace):
                    if (link := entry.find('atom:id', namespace)) is not None and link.text:
                        urls.append(link.text)
                return urls
        except (requests.exceptions.RequestException, ET.ParseError, ValueError):
            pass
        return []

    def _search_online(self, query, attempt=0):
        """Search online using configured search engine with automatic fallback"""
        if self.serpapi_key:
            return self._search_serpapi(query)
        
        if self.search_engine == 'serpapi':
            print(f"    ⚠️ SerpApi selected but no API key found")
            return []
        elif self.search_engine == 'duckduckgo' or self.search_engine == 'auto':
            results = self._search_duckduckgo(query, attempt)
            if not results and not self.duckduckgo_failed:
                self.duckduckgo_failed = True
            return results
        else:
            return []

    def _search_serpapi(self, query):
        """Search using SerpApi (Google Search via SerpApi API)"""
        if not self.serpapi_key:
            return []

        try:
            params = {
                'api_key': self.serpapi_key,
                'engine': 'google',
                'q': query[:200],
                'num': 5,
                'hl': 'en',
                'gl': 'us'
            }
            
            response = requests.get('https://serpapi.com/search', params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                results = []
                
                for item in data.get('organic_results', []):
                    if url_result := item.get('link'):
                        if self._should_include_url(url_result):
                            results.append(url_result)
                
                return results
            elif response.status_code == 429:
                print(f"    Warning: SerpApi rate limit exceeded")
                return []
            elif response.status_code == 401:
                print(f"    Warning: SerpApi key invalid")
                self.serpapi_key = None
                return []
            else:
                print(f"    Warning: SerpApi returned HTTP {response.status_code}")
                return []
        except requests.exceptions.RequestException as e:
            print(f"    Warning: SerpApi request failed: {str(e)[:50]}")
            return []
        except (ValueError, KeyError) as e:
            print(f"    Warning: Failed to parse SerpApi response: {str(e)[:50]}")
            return []

    def _search_duckduckgo(self, query, attempt=0):
        """Search using DuckDuckGo HTML scraping"""
        query_clean = re.sub(r'[^\w\s]', '', query)
        query_encoded = quote_plus(query_clean[:100])
        
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        ]
        
        headers = {
            'User-Agent': user_agents[attempt % len(user_agents)],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        results = []
        
        for retry in range(2):
            try:
                url = f"https://html.duckduckgo.com/html/?q={query_encoded}"
                response = self.session.get(url, headers=headers, timeout=20)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    for result in soup.find_all('a', class_='result__a', limit=5):
                        if (href := result.get('href')) and href.startswith('http'):
                            if self._should_include_url(href):
                                results.append(href)
                    
                    if results:
                        return results
                    
                elif response.status_code in [202, 429]:
                    print(f"    DuckDuckGo rate limiting detected ({response.status_code})")
                    self.duckduckgo_failed = True
                    return []
            except requests.exceptions.RequestException:
                if retry < 1:
                    time.sleep(3)
                    continue
        
        return results