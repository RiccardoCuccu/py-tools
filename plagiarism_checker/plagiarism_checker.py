"""
Plagiarism Checker

This script detects potential plagiarism in Word documents and PDFs by searching for 
similar content online, downloading matching sources, and performing text similarity 
analysis.

USAGE:
    python plagiarism_checker.py path/to/document.docx
    python plagiarism_checker.py path/to/document.pdf

WORKFLOW:
    1. Extracts text from the Word document
    2. Identifies key phrases and searches for them online
    3. Downloads content from matching URLs
    4. Compares the document against downloaded sources
    5. Generates a detailed report with similarity scores

OUTPUT:
    - Console report showing matched sources and similarity percentages
    - Text file report saved in the same directory as the input document
    - Downloaded sources cached for future reference

REQUIREMENTS:
    - python-docx: pip install python-docx
    - PyMuPDF: pip install PyMuPDF
    - requests: pip install requests
    - beautifulsoup4: pip install beautifulsoup4
    - scikit-learn: pip install scikit-learn
    - nltk: pip install nltk

LIMITATIONS:
    - Only detects textual similarities (no paraphrasing detection)
    - Only searches publicly accessible web content
    - Does not access academic databases or paywalled content
    - Search rate limited to avoid IP blocking
"""

import sys
import os
import re
import time
import json
import hashlib
from pathlib import Path
from urllib.parse import urlparse, urljoin, quote_plus
from datetime import datetime

# Fix Windows console encoding issues
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

try:
    import requests
    from bs4 import BeautifulSoup
    from docx import Document
    import fitz  # PyMuPDF
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import nltk
    from nltk.corpus import stopwords
    from nltk.tokenize import sent_tokenize
except ImportError as e:
    print(f"Error: Missing required library - {e}")
    print("\nPlease install all dependencies:")
    print("pip install python-docx PyMuPDF requests beautifulsoup4 scikit-learn nltk")
    sys.exit(1)

# Download NLTK data if not present
try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    print("Downloading required NLTK data...")
    nltk.download('punkt_tab', quiet=True)

try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    print("Downloading stopwords data...")
    nltk.download('stopwords', quiet=True)

class PlagiarismChecker:
    def __init__(self, doc_path, max_sources=30, min_phrase_words=8, extract_pages=None, page_position='middle', num_phrases=None):
        self.doc_path = Path(doc_path)
        self.max_sources = max_sources
        self.min_phrase_words = min_phrase_words
        self.extract_pages = extract_pages  # Number of pages to extract (None = all)
        self.page_position = page_position  # 'start', 'middle', or 'end'
        self.num_phrases = num_phrases  # Number of key phrases to extract (None = auto-scale)
        self.cache_dir = self.doc_path.parent / ".plagiarism_cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.stop_words = set(stopwords.words('english'))
        
    def extract_text_from_docx(self):
        """Extract text from a Word document (optionally from specific pages)"""
        print(f"\n[1/5] Extracting text from document: {self.doc_path.name}")
        try:
            doc = Document(self.doc_path)
            all_paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]

            if self.extract_pages is None:
                # Extract all text
                text = '\n'.join(all_paragraphs)
                print(f"✓ Extracted {len(text)} characters from entire document")
            else:
                # Estimate pages based on character count (approx 3000 chars per page)
                CHARS_PER_PAGE = 3000
                total_chars = sum(len(p) for p in all_paragraphs)
                total_pages = max(1, total_chars // CHARS_PER_PAGE)

                # Calculate which paragraphs to extract
                chars_to_extract = self.extract_pages * CHARS_PER_PAGE

                if self.page_position == 'start':
                    start_char = 0
                elif self.page_position == 'end':
                    start_char = max(0, total_chars - chars_to_extract)
                else:  # middle
                    start_char = max(0, (total_chars - chars_to_extract) // 2)

                end_char = start_char + chars_to_extract

                # Extract paragraphs within the range
                selected_paragraphs = []
                current_char = 0
                for para in all_paragraphs:
                    para_end = current_char + len(para)
                    if para_end > start_char and current_char < end_char:
                        selected_paragraphs.append(para)
                    current_char = para_end + 1  # +1 for newline
                    if current_char >= end_char:
                        break

                text = '\n'.join(selected_paragraphs)
                print(f"✓ Extracted {len(text)} characters from {self.extract_pages} pages ({self.page_position}) out of ~{total_pages} total pages")

            return text
        except Exception as e:
            print(f"✗ Error reading document: {e}")
            sys.exit(1)
    
    def extract_text_from_pdf(self):
        """Extract all text from a PDF document"""
        print(f"\n[1/5] Extracting text from PDF: {self.doc_path.name}")
        try:
            doc = fitz.open(self.doc_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            print(f"✓ Extracted {len(text)} characters from {len(doc)} pages")
            return text
        except Exception as e:
            print(f"✗ Error reading PDF: {e}")
            sys.exit(1)
    
    def extract_text(self):
        """Extract text based on file extension"""
        if self.doc_path.suffix.lower() == '.docx':
            return self.extract_text_from_docx()
        elif self.doc_path.suffix.lower() == '.pdf':
            return self.extract_text_from_pdf()
        else:
            print(f"✗ Error: Unsupported file format: {self.doc_path.suffix}")
            print("Supported formats: .docx, .pdf")
            sys.exit(1)
    
    def extract_key_phrases(self, text):
        """Extract key phrases from text for searching using TF-IDF scoring"""
        print(f"\n[2/5] Extracting key phrases for search...")

        # Calculate number of phrases based on document length
        if self.num_phrases:
            num_phrases = self.num_phrases
        else:
            # Auto-scale: 1 phrase per page (estimated at 3000 chars per page)
            estimated_pages = max(1, len(text) // 3000)
            num_phrases = max(5, min(estimated_pages, 20))  # Between 5 and 20 phrases

        print(f"  Target: {num_phrases} key phrases")

        # Split into sentences
        sentences = sent_tokenize(text)

        # Filter sentences: remove too short, too long, or with too many common words
        filtered_sentences = []
        for sent in sentences:
            words = sent.split()
            if self.min_phrase_words <= len(words) <= 20:
                # Check if sentence has enough meaningful words
                meaningful_words = [w for w in words if w.lower() not in self.stop_words]
                if len(meaningful_words) >= self.min_phrase_words / 2:
                    filtered_sentences.append(sent)

        if not filtered_sentences:
            print("  Warning: No suitable sentences found, using original text")
            return [text[:200]]  # Fallback to first 200 chars

        # Use TF-IDF to score sentences and select the most distinctive ones
        if len(filtered_sentences) <= num_phrases:
            phrases = filtered_sentences
        else:
            # Calculate TF-IDF scores for each sentence
            try:
                vectorizer = TfidfVectorizer(stop_words='english', max_features=100)
                tfidf_matrix = vectorizer.fit_transform(filtered_sentences)

                # Calculate importance score for each sentence (sum of TF-IDF values)
                sentence_scores = []
                for i in range(len(filtered_sentences)):
                    # Convert sparse row to array and sum
                    score = tfidf_matrix[i].toarray().sum()
                    sentence_scores.append((score, i))

                # Sort by score (descending) to get most distinctive sentences
                sentence_scores.sort(reverse=True, key=lambda x: x[0])

                # Select top scoring sentences, but maintain document order
                top_indices = sorted([idx for _, idx in sentence_scores[:num_phrases * 2]])

                # Select evenly distributed from top candidates
                step = len(top_indices) // num_phrases if len(top_indices) >= num_phrases else 1
                selected_indices = [top_indices[i * step] for i in range(min(num_phrases, len(top_indices)))]

                phrases = [filtered_sentences[idx] for idx in sorted(selected_indices)]

            except Exception as e:
                print(f"  Warning: TF-IDF scoring failed ({str(e)}), using fallback distribution")
                # Fallback to uniform distribution
                step = len(filtered_sentences) // num_phrases
                phrases = [filtered_sentences[i * step] for i in range(num_phrases)]

        print(f"✓ Selected {len(phrases)} key phrases for searching")
        return phrases
    
    def search_online(self, query):
        """Perform a web search and return URLs (using DuckDuckGo HTML scraping)"""
        # Clean and encode query
        query_clean = re.sub(r'[^\w\s]', '', query)
        query_encoded = quote_plus(query_clean[:100])  # Limit query length
        
        # Use DuckDuckGo HTML (no API key needed)
        url = f"https://html.duckduckgo.com/html/?q={query_encoded}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, 'html.parser')
            results = []
            
            # Extract results from DuckDuckGo HTML
            for result in soup.find_all('a', class_='result__a', limit=5):
                href = result.get('href')
                if href and href.startswith('http'):
                    # Filter out common non-content URLs
                    if not any(x in href.lower() for x in ['youtube.com', 'facebook.com', 'twitter.com', 'instagram.com']):
                        results.append(href)
            
            return results
        except Exception as e:
            print(f"  Warning: Search failed for query: {str(e)}")
            return []
    
    def search_all_phrases(self, phrases):
        """Search for all key phrases and collect unique URLs"""
        print(f"\n[3/5] Searching online for similar content...")
        all_urls = set()
        
        for i, phrase in enumerate(phrases, 1):
            print(f"  Searching phrase {i}/{len(phrases)}: \"{phrase[:50]}...\"")
            urls = self.search_online(phrase)
            all_urls.update(urls)
            time.sleep(2)  # Rate limiting to avoid being blocked
            
            if len(all_urls) >= self.max_sources:
                break
        
        unique_urls = list(all_urls)[:self.max_sources]
        print(f"✓ Found {len(unique_urls)} unique sources to analyze")
        return unique_urls
    
    def _extract_text_from_html(self, html_content):
        """Extract and clean text from HTML content"""
        soup = BeautifulSoup(html_content, 'html.parser')

        # Remove script and style elements
        for script in soup(['script', 'style', 'nav', 'header', 'footer']):
            script.decompose()

        # Get text
        text = soup.get_text(separator=' ', strip=True)

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)

        return text

    def _download_method_1(self, url, timeout):
        """Download method 1: Standard desktop User-Agent"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            return self._extract_text_from_html(response.content)
        return None

    def _download_method_2(self, url, timeout):
        """Download method 2: Mobile User-Agent with additional headers"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1'
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            return self._extract_text_from_html(response.content)
        return None

    def _download_method_3(self, url, timeout):
        """Download method 3: Session with cookies and referrer"""
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.google.com/'
        }
        response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if response.status_code == 200:
            return self._extract_text_from_html(response.content)
        return None

    def download_content(self, url):
        """Download and extract text content from a URL with multi-method retry strategy"""
        # Check cache first
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_file = self.cache_dir / f"{url_hash}.txt"

        if cache_file.exists():
            return cache_file.read_text(encoding='utf-8', errors='ignore'), None

        # Define download methods and retry strategy
        methods = [self._download_method_1, self._download_method_2, self._download_method_3]
        timeouts = [15, 25, 35]  # Increasing timeouts for each attempt
        delays = [2, 5, 10]  # Increasing delays between attempts

        last_error = None

        # 3 attempts with rotating methods
        for attempt in range(3):
            method = methods[attempt % len(methods)]
            timeout = timeouts[attempt]

            try:
                text = method(url, timeout)
                if text and len(text) > 0:
                    # Cache the content
                    cache_file.write_text(text, encoding='utf-8', errors='ignore')
                    return text, None
            except Exception as e:
                last_error = str(e)
                print(f"    Attempt {attempt + 1}/3 failed (method {(attempt % 3) + 1}): {last_error[:50]}...")

            # Wait before next attempt (except after last attempt)
            if attempt < 2:
                time.sleep(delays[attempt])

        # All attempts failed
        return None, last_error if last_error else "Unknown error"
    
    def download_all_sources(self, urls):
        """Download content from all URLs and track failures"""
        print(f"\n[4/5] Downloading content from sources...")
        sources = []
        failed_sources = []

        for i, url in enumerate(urls, 1):
            print(f"  Downloading {i}/{len(urls)}: {url[:60]}...")
            content, error = self.download_content(url)

            if content and len(content) > 200:  # Minimum content length
                sources.append({
                    'url': url,
                    'content': content,
                    'title': self.extract_title(content)
                })
            else:
                # Track failed download
                reason = error if error else "Content too short (< 200 characters)"
                failed_sources.append({
                    'url': url,
                    'reason': reason
                })
                print(f"    ✗ Failed: {reason[:50]}...")

            time.sleep(1)  # Rate limiting

        print(f"✓ Successfully downloaded {len(sources)} sources")
        if failed_sources:
            print(f"✗ Failed to download {len(failed_sources)} sources")
        return sources, failed_sources
    
    def extract_title(self, text):
        """Extract a reasonable title from text"""
        # Take first meaningful sentence, max 100 chars
        sentences = sent_tokenize(text[:500])
        if sentences:
            title = sentences[0][:100]
            return title if len(title) > 10 else "Untitled Source"
        return "Untitled Source"
    
    def calculate_similarity(self, text1, text2):
        """Calculate cosine similarity between two texts"""
        try:
            vectorizer = TfidfVectorizer(stop_words='english', max_features=1000)
            tfidf_matrix = vectorizer.fit_transform([text1, text2])
            similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            return similarity
        except:
            return 0.0
    
    def find_matching_segments(self, doc_text, source_text, threshold=0.7):
        """Find matching text segments between document and source"""
        doc_sentences = sent_tokenize(doc_text)
        source_sentences = sent_tokenize(source_text)
        
        matches = []
        
        for doc_sent in doc_sentences:
            if len(doc_sent.split()) < 5:  # Skip very short sentences
                continue
                
            for source_sent in source_sentences:
                if len(source_sent.split()) < 5:
                    continue
                    
                similarity = self.calculate_similarity(doc_sent, source_sent)
                
                if similarity >= threshold:
                    matches.append({
                        'doc_text': doc_sent,
                        'source_text': source_sent,
                        'similarity': similarity
                    })
                    break  # Move to next document sentence
        
        return matches
    
    def analyze_sources(self, doc_text, sources):
        """Analyze all sources against the document"""
        print(f"\n[5/5] Analyzing similarity with downloaded sources...")
        results = []
        
        for i, source in enumerate(sources, 1):
            print(f"  Analyzing source {i}/{len(sources)}...")
            
            # Calculate overall similarity
            overall_similarity = self.calculate_similarity(doc_text, source['content'])
            
            # Find specific matching segments
            matches = self.find_matching_segments(doc_text, source['content'])
            
            if overall_similarity >= 0.01 or len(matches) > 0:  # Include if similarity >= 1% or has matches
                results.append({
                    'url': source['url'],
                    'title': source['title'],
                    'overall_similarity': overall_similarity,
                    'matching_segments': len(matches),
                    'matches': matches[:5]  # Keep top 5 matches
                })
        
        # Sort by similarity
        results.sort(key=lambda x: x['overall_similarity'], reverse=True)
        
        print(f"✓ Analysis complete")
        return results
    
    def generate_report(self, results, doc_text, failed_sources=None):
        """Generate and save plagiarism report"""
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("PLAGIARISM CHECK REPORT")
        report_lines.append("=" * 80)
        report_lines.append(f"Document: {self.doc_path.name}")
        report_lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"Document length: {len(doc_text)} characters")
        report_lines.append(f"Sources analyzed: {len(results)}")
        if failed_sources:
            report_lines.append(f"Sources failed to download: {len(failed_sources)}")
        report_lines.append("=" * 80)
        
        if not results:
            report_lines.append("\n✓ NO SIGNIFICANT MATCHES FOUND")
            report_lines.append("\nThe document appears to be original or no similar sources were found online.")
        else:
            max_similarity = results[0]['overall_similarity'] if results else 0
            total_segments = sum(r['matching_segments'] for r in results)
            
            report_lines.append(f"\nOVERALL ASSESSMENT:")
            report_lines.append(f"  Highest similarity score: {max_similarity*100:.1f}%")
            report_lines.append(f"  Total matching segments found: {total_segments}")
            
            if max_similarity > 0.5:
                report_lines.append(f"  Status: ⚠ HIGH SIMILARITY DETECTED")
            elif max_similarity > 0.3:
                report_lines.append(f"  Status: ⚠ MODERATE SIMILARITY DETECTED")
            else:
                report_lines.append(f"  Status: ✓ LOW SIMILARITY")
            
            report_lines.append("\n" + "=" * 80)
            report_lines.append("DETAILED RESULTS")
            report_lines.append("=" * 80)
            
            for i, result in enumerate(results, 1):
                report_lines.append(f"\nSOURCE #{i}")
                report_lines.append(f"  URL: {result['url']}")
                report_lines.append(f"  Title: {result['title']}")
                report_lines.append(f"  Overall Similarity: {result['overall_similarity']*100:.1f}%")
                report_lines.append(f"  Matching Segments: {result['matching_segments']}")
                
                if result['matches']:
                    report_lines.append(f"\n  Sample Matches:")
                    for j, match in enumerate(result['matches'][:3], 1):
                        report_lines.append(f"\n  Match {j} (Similarity: {match['similarity']*100:.1f}%):")
                        report_lines.append(f"    Document: \"{match['doc_text'][:150]}...\"")
                        report_lines.append(f"    Source:   \"{match['source_text'][:150]}...\"")
                
                report_lines.append("\n" + "-" * 80)

        # Add section for failed downloads
        if failed_sources:
            report_lines.append("\n" + "=" * 80)
            report_lines.append("SOURCES NOT DOWNLOADED")
            report_lines.append("=" * 80)
            report_lines.append("\nThe following sources could not be downloaded after 3 attempts.")
            report_lines.append("Please verify these sources manually:\n")

            for i, failed in enumerate(failed_sources, 1):
                report_lines.append(f"\nFAILED SOURCE #{i}")
                report_lines.append(f"  URL: {failed['url']}")
                report_lines.append(f"  Reason: {failed['reason']}")
                report_lines.append("-" * 80)

        report_lines.append("\n" + "=" * 80)
        report_lines.append("LIMITATIONS")
        report_lines.append("=" * 80)
        report_lines.append("- This tool only detects textual similarities")
        report_lines.append("- Does NOT detect paraphrasing or semantic rewording")
        report_lines.append("- Only searches publicly accessible web content")
        report_lines.append("- Does NOT access academic databases or paywalled sources")
        report_lines.append("=" * 80)
        
        report_text = '\n'.join(report_lines)
        
        # Save report
        report_file = self.doc_path.parent / f"{self.doc_path.stem}_plagiarism_report.txt"
        report_file.write_text(report_text, encoding='utf-8')
        
        # Print to console
        print("\n" + report_text)
        print(f"\n✓ Report saved to: {report_file}")
        
    def check(self):
        """Main workflow to check for plagiarism"""
        print("=" * 80)
        print("PLAGIARISM CHECKER")
        print("=" * 80)

        # Warning if analyzing entire document
        if self.extract_pages is None:
            print("\n⚠ WARNING: Analyzing entire document")
            print("  - Analyzing the full document may reduce detection accuracy")
            print("  - Key phrases might be too generic or miss specific sections")
            print("  - Consider using --pages option to focus on specific sections")
            print("  - Example: --pages 3 --position middle")
            print()

            # Ask for confirmation
            while True:
                response = input("Do you want to continue? (y/n): ").lower().strip()
                if response in ['y', 'yes']:
                    print()
                    break
                elif response in ['n', 'no']:
                    print("Analysis cancelled by user.")
                    sys.exit(0)
                else:
                    print("Please enter 'y' or 'n'")

        # Step 1: Extract text from document
        doc_text = self.extract_text()
        
        if len(doc_text) < 100:
            print("\n✗ Error: Document is too short for meaningful analysis")
            sys.exit(1)
        
        # Step 2: Extract key phrases
        phrases = self.extract_key_phrases(doc_text)
        
        # Step 3: Search for similar content online
        urls = self.search_all_phrases(phrases)
        
        if not urls:
            print("\n⚠ Warning: No sources found online. Cannot perform comparison.")
            print("This might mean the document is original, or search failed.")
            sys.exit(0)
        
        # Step 4: Download sources
        sources, failed_sources = self.download_all_sources(urls)

        if not sources:
            print("\n⚠ Warning: Could not download any sources. Cannot perform comparison.")
            if failed_sources:
                print(f"All {len(failed_sources)} sources failed to download.")
            sys.exit(0)

        # Step 5: Analyze similarity
        results = self.analyze_sources(doc_text, sources)

        # Generate report
        self.generate_report(results, doc_text, failed_sources)

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Check documents for plagiarism by searching online sources',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python plagiarism_checker.py my_essay.docx
  python plagiarism_checker.py research_paper.pdf
  python plagiarism_checker.py document.docx --pages 3 --position middle
  python plagiarism_checker.py document.docx --pages 5 --position start
        """
    )

    parser.add_argument('file', help='Path to the document (.docx or .pdf)')
    parser.add_argument('--pages', type=int, default=None,
                        help='Number of pages to extract (default: all)')
    parser.add_argument('--position', choices=['start', 'middle', 'end'], default='middle',
                        help='Position to extract pages from (default: middle)')
    parser.add_argument('--max-sources', type=int, default=30,
                        help='Maximum number of sources to check (default: 30)')
    parser.add_argument('--num-phrases', type=int, default=None,
                        help='Number of key phrases to extract (default: auto-scale, 1 per page)')

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}")
        sys.exit(1)

    if not (args.file.endswith('.docx') or args.file.endswith('.pdf')):
        print("Error: File must be a .docx or .pdf document")
        print("Supported formats: .docx, .pdf")
        sys.exit(1)

    checker = PlagiarismChecker(
        args.file,
        max_sources=args.max_sources,
        extract_pages=args.pages,
        page_position=args.position,
        num_phrases=args.num_phrases
    )
    checker.check()

if __name__ == "__main__":
    main()