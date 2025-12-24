"""
Plagiarism Checker - Main Entry Point

This is the main script that orchestrates the 5-step plagiarism detection workflow.
"""

import sys
import os
from pathlib import Path

from extractors import TextExtractor
from phrase_selector import PhraseSelector
from search_engines import SearchEngineManager
from downloader import ContentDownloader
from analyzer import SimilarityAnalyzer


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def confirm_continue(message="Do you want to continue?"):
    """Prompt user for y/n confirmation, exit on 'n'"""
    while True:
        response = input(f"{message} (y/n): ").lower().strip()
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no']:
            print("Analysis cancelled by user.")
            sys.exit(0)
        else:
            print("Please enter 'y' or 'n'")


# ============================================================================
# MAIN PLAGIARISM CHECKER CLASS
# ============================================================================

class PlagiarismChecker:
    def __init__(self, doc_path, max_sources=5, min_phrase_words=8, extract_pages=None, 
                 page_position='middle', num_phrases=None, use_apis=False, use_local=False, 
                 search_engine='auto', cache_only=False):
        """Initialize the plagiarism checker with configuration parameters"""
        self.doc_path = Path(doc_path)
        self.max_sources = max_sources
        self.extract_pages = extract_pages
        self.page_position = page_position
        self.num_phrases = num_phrases
        self.use_apis = use_apis
        self.use_local = use_local
        self.search_engine = search_engine
        self.cache_only = cache_only
        
        # Initialize component modules
        self.extractor = TextExtractor(doc_path, extract_pages, page_position)
        self.phrase_selector = PhraseSelector(min_phrase_words, num_phrases)
        self.search_manager = SearchEngineManager(search_engine, use_apis, use_local, doc_path)
        self.downloader = ContentDownloader(doc_path, cache_only)
        self.analyzer = SimilarityAnalyzer(doc_path)
    
    def check(self):
        """Main workflow orchestrating the 5-step plagiarism check process"""
        print("=" * 80)
        print("PLAGIARISM CHECKER")
        print("=" * 80)

        # Warn if cache-only mode
        if self.cache_only:
            print("\n" + "ℹ️ " * 20)
            print("CACHE-ONLY MODE ENABLED")
            print("ℹ️ " * 20)
            print("\nOnly cached sources will be used. No new downloads will be performed.")
            print("This is useful for re-analysis or when network is unavailable.")
            print("\n" + "ℹ️ " * 20 + "\n")

        # Warn if no SerpApi key and not using local-only mode
        if not self.search_manager.serpapi_key and not self.use_local and not self.cache_only:
            print("\n" + "⚠️ " * 20)
            print("WARNING: NO SERPAPI KEY DETECTED")
            print("⚠️ " * 20)
            print("\nDuckDuckGo blocks requests after 3-5 searches, making online")
            print("plagiarism detection essentially non-functional without SerpApi.")
            print("\nYour options:")
            print("  1. Set up SerpApi (free tier available)")
            print("     - Visit: https://serpapi.com/")
            print("     - The script will prompt you to enter your API key")
            print("  2. Use --use-local to check only against local reference files")
            print("  3. Use --cache-only to analyze only previously cached sources")
            print("\n" + "⚠️ " * 20 + "\n")
            
            confirm_continue("Continue anyway (online search will likely fail)?")
            print()

        # Warn user if analyzing entire document (less accurate)
        if self.extract_pages is None:
            print("\n⚠️ WARNING: Analyzing entire document")
            print("  - Analyzing the full document may reduce detection accuracy")
            print("  - Key phrases might be too generic or miss specific sections")
            print("  - Consider using --pages option to focus on specific sections")
            print("  - Example: --pages 3 --position middle")
            print()

            confirm_continue()
            print()

        # STEP 1: Extract text from document
        doc_text = self.extractor.extract_text()
        
        if len(doc_text) < 100:
            print("\n✗ Error: Document is too short for meaningful analysis")
            sys.exit(1)
        
        # STEP 2: Extract key phrases for searching
        phrases = self.phrase_selector.extract_key_phrases(doc_text)

        # STEP 3: Search for similar content online and load local sources
        if self.cache_only:
            print(f"\n[3/5] Skipping search (cache-only mode)...")
            all_sources = []
            failed_sources = []
        else:
            all_sources, failed_sources = self.search_manager.search_and_load(phrases, self.max_sources)

            if not all_sources:
                print("\n" + "=" * 80)
                print("⚠ WARNING: No sources found")
                print("=" * 80)
                print("\nNo sources were found for the extracted phrases.")
                print("\nPossible reasons:")
                print("  1. The document content is very original or unique")
                print("  2. The key phrases are too generic or too specific")
                print("  3. Search engine is blocking requests (DuckDuckGo rate limiting)")
                print("  4. Network connectivity issues")
                print("\nSuggestions:")
                if not self.search_manager.serpapi_key:
                    print("  - Set up SerpApi (script will prompt you)")
                print("  - Restart your router to get a new IP (if using DuckDuckGo)")
                print("  - Use --use-apis flag to search academic databases")
                print("  - Use --use-local to compare with local reference files")
                print("  - Use --cache-only to analyze previously cached sources")
                print("  - Try analyzing a different section with --pages and --position")
                print("=" * 80)
                sys.exit(0)

        # STEP 4: Download content from found URLs
        if self.cache_only:
            print(f"\n[4/5] Loading cached sources only...")
            online_sources = self.downloader.get_cached_sources(all_sources)
            download_failures = []
            
            if not online_sources:
                print("  ⚠ Warning: No cached sources found")
                print("  Run without --cache-only to download sources first")
        else:
            online_sources, download_failures = self.downloader.download_all_sources(all_sources)
        
        # Combine with local sources (already loaded in search_manager)
        local_sources = self.search_manager.local_sources
        combined_sources = local_sources + online_sources

        if not combined_sources:
            print("\n⚠ Warning: Could not access any sources. Cannot perform comparison.")
            if download_failures:
                print(f"All {len(download_failures)} online sources failed to download.")
            sys.exit(0)

        print(f"\n✓ Total sources to analyze: {len(combined_sources)} ({len(local_sources)} local, {len(online_sources)} online)")

        # STEP 5: Analyze similarity and generate report
        results = self.analyzer.analyze_sources(doc_text, combined_sources)
        self.analyzer.generate_report(results, doc_text, download_failures, len(local_sources))


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def validate_file(file_path):
    """Validate file exists and is accessible"""
    file_path = Path(file_path)
    
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    
    if not file_path.is_file():
        print(f"Error: Path is not a file: {file_path}")
        sys.exit(1)
    
    if not os.access(file_path, os.R_OK):
        print(f"Error: File not readable (check permissions): {file_path}")
        sys.exit(1)
    
    if file_path.stat().st_size == 0:
        print(f"Error: File is empty: {file_path}")
        sys.exit(1)
    
    # Warn about very large files
    if file_path.stat().st_size > 100 * 1024 * 1024:  # 100MB
        print(f"Warning: File is very large ({file_path.stat().st_size / 1024 / 1024:.1f}MB)")
        confirm_continue("Processing may take a long time. Continue?")

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Check documents for plagiarism by searching online sources',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py my_essay.docx
  python main.py research_paper.pdf
  python main.py notes.txt
  python main.py document.docx --pages 3 --position middle
  python main.py document.docx --pages 5 --position start
  python main.py document.docx --cache-only  # Use only cached sources
        """
    )

    parser.add_argument('file', nargs='?', default=None, help='Path to the document (.docx, .pdf or .txt)')
    parser.add_argument('--pages', type=int, default=None,
                        help='Number of pages to extract (default: all)')
    parser.add_argument('--position', choices=['start', 'middle', 'end'], default='middle',
                        help='Position to extract pages from (default: middle)')
    parser.add_argument('--max-sources', type=int, default=5,
                        help='Maximum number of sources to check (default: 5)')
    parser.add_argument('--num-phrases', type=int, default=None,
                        help='Number of key phrases to extract (default: auto-scale, 1 per page, use 0 for ALL phrases)')
    parser.add_argument('--use-apis', action='store_true',
                        help='Search academic APIs (CrossRef, arXiv, Semantic Scholar) in addition to web search')
    parser.add_argument('--use-local', action='store_true',
                        help='Compare with local reference files in "local_references" folder')
    parser.add_argument('--search-engine', choices=['auto', 'duckduckgo', 'serpapi'], default='auto',
                        help='Search engine to use: auto (SerpApi if configured, else DuckDuckGo), duckduckgo, serpapi (default: auto).')
    parser.add_argument('--cache-only', action='store_true',
                        help='Use only cached sources without downloading new ones (useful for re-analysis)')

    args = parser.parse_args()

    # Validate that a file was provided
    if args.file is None:
        print("=" * 80)
        print("ERROR: No file specified")
        print("=" * 80)
        print("\nUsage: python main.py <document_file>\n")
        print("Examples:")
        print("  python main.py my_essay.docx")
        print("  python main.py research_paper.pdf")
        print("  python main.py notes.txt")
        print("\nSupported formats: .docx, .pdf, .txt")
        print("\nFor more options, use: python main.py --help")
        print("=" * 80)
        sys.exit(1)

    # Validate file format
    if not (args.file.endswith('.docx') or args.file.endswith('.pdf') or args.file.endswith('.txt')):
        print("Error: File must be a .docx, .pdf or .txt document")
        print("Supported formats: .docx, .pdf, .txt")
        sys.exit(1)

    # Validate file exists and is accessible
    validate_file(args.file)

    # Initialize and run plagiarism checker
    checker = PlagiarismChecker(
        args.file,
        max_sources=args.max_sources,
        extract_pages=args.pages,
        page_position=args.position,
        num_phrases=args.num_phrases,
        use_apis=args.use_apis,
        use_local=args.use_local,
        search_engine=args.search_engine,
        cache_only=args.cache_only
    )
    checker.check()

if __name__ == "__main__":
    main()