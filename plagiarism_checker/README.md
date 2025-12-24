# Plagiarism Checker

**Purpose:** `plagiarism_checker.py` is a tool designed to detect potential plagiarism in Word documents, PDFs and text files by searching for similar content online, downloading matching sources, and performing text similarity analysis. The tool automates the entire process of identifying suspicious content and generates a detailed report with similarity scores.

## How it Works

- Extracts text from .docx, .pdf or .txt files (full document or specific pages)
- Uses TF-IDF scoring to identify the most distinctive phrases (auto-scales: 1 phrase per page)
- Searches online using SerpApi (recommended) or DuckDuckGo fallback for up to 5 sources (configurable)
- Optionally searches academic APIs (CrossRef, arXiv, Semantic Scholar, Unpaywall) with `--use-apis` flag
- Optionally compares against local reference files in `local_references` folder with `--use-local` flag
- Uses API-first approach for academic sources (arXiv, DOI, Semantic Scholar) with intelligent fallbacks
- Attempts multiple download methods with retries and increasing timeouts for each source
- Calculates similarity scores using TF-IDF and cosine similarity (includes sources ≥ 1%)
- Creates detailed report with similarity scores, matching segments, and failed download links

## Usage
```
# Basic usage - Check entire document
python main.py document.docx
python main.py document.pdf
python main.py document.txt

# Check specific pages from a position (works with all formats)
python main.py document.docx --pages 3 --position middle
python main.py document.pdf --pages 5 --position start
python main.py document.txt --pages 5 --position end

# Use academic APIs for better coverage
python main.py document.docx --pages 3 --use-apis

# Compare with local reference files
python main.py document.docx --use-local

# Combine local references with online search and APIs
python main.py document.docx --pages 3 --use-local --use-apis

# Use only cached sources (no new downloads)
python main.py document.docx --cache-only

# Extract ALL relevant phrases (WARNING: very slow)
python main.py document.docx --num-phrases 0

# Extract specific number of phrases
python main.py document.docx --num-phrases 15

# Use specific search engine
python main.py document.docx --search-engine serpapi
python main.py document.docx --search-engine duckduckgo
```

### Options

- `--pages N` - Extract N pages instead of entire document (works for all formats: .docx, .pdf, .txt)
- `--position` - Extract from `start`, `middle`, or `end` (default: middle)
- `--max-sources N` - Maximum sources to check (default: 5)
- `--num-phrases N` - Number of key phrases to extract:
  - Not specified: auto-scale (1 per page, min 5, max 20)
  - `N > 0`: extract exactly N phrases
  - `0`: extract ALL relevant phrases (WARNING: significantly increases processing time)
- `--use-apis` - Search academic APIs (CrossRef, arXiv, Semantic Scholar) in addition to web search
- `--use-local` - Compare with local reference files (.docx, .pdf, .txt) in `local_references` folder
- `--search-engine` - Choose search engine:
  - `auto` (default): SerpApi if configured, otherwise DuckDuckGo
  - `serpapi`: Use only SerpApi (requires API key)
  - `duckduckgo`: Use only DuckDuckGo (not recommended - severe rate limiting)
- `--cache-only` - Use only cached sources without downloading new ones (useful for re-analysis or testing)

The script will automatically search online, download sources, analyze similarities, and generate a report saved as `<filename>_plagiarism_report.txt` in the script directory.

## Installation

To use `plagiarism_checker.py`, you'll need to install the following Python libraries:

```
pip install python-docx PyMuPDF requests beautifulsoup4 scikit-learn nltk
```

See [SETUP.md](SETUP.md) for detailed setup instructions, including SerpApi configuration (recommended for reliable results).

## Limitations

- DuckDuckGo may rate-limit requests from the same IP address. Solutions:
  - Use SerpApi (recommended, 100 free searches/month - see [SETUP.md](SETUP.md))
  - Use `--use-local` to compare with local files only
  - Wait 30-60 minutes and retry (often ineffective)
  - Restart your router to get a new IP (temporary solution)
- Only detects textual similarities (no paraphrasing or semantic rewording detection)
- Only searches publicly accessible web content
- Academic databases and paywalled content require `--use-apis` flag
- Some publishers block automated access despite API fallbacks (403 Forbidden errors)
- Results depend on the quality and availability of online sources