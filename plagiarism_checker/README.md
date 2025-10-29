# Plagiarism Checker

**Purpose:** `plagiarism_checker.py` is a script designed to detect potential plagiarism in Word documents and PDFs by searching for similar content online, downloading matching sources, and performing text similarity analysis. The tool automates the entire process of identifying suspicious content and generates a detailed report with similarity scores.

## How it Works

- Extracts text from .docx or .pdf files (full document or specific pages)
- Uses TF-IDF scoring to identify the most distinctive phrases (auto-scales: 1 phrase per page)
- Searches DuckDuckGo for up to 30 similar sources (configurable)
- Optionally searches academic APIs (CrossRef, arXiv, Semantic Scholar) with `--use-apis` flag
- Optionally compares against local reference files in `local_references` folder with `--use-local` flag
- Attempts 3 different download methods with retries and increasing timeouts for each source
- Calculates similarity scores using TF-IDF and cosine similarity (includes sources ≥ 1%)
- Creates detailed report with similarity scores, matching segments, and failed download links

## Usage

```bash
# Check entire document
python plagiarism_checker.py path/to/document.docx
python plagiarism_checker.py path/to/document.pdf

# Check specific pages from a position
python plagiarism_checker.py document.docx --pages 3 --position middle
python plagiarism_checker.py document.docx --pages 5 --position start

# Use academic APIs for better coverage
python plagiarism_checker.py document.docx --pages 3 --use-apis

# Compare with local reference files
python plagiarism_checker.py document.docx --use-local

# Combine local references with online search and APIs
python plagiarism_checker.py document.docx --pages 3 --use-local --use-apis
```

Options:
- `--pages N` - Extract N pages instead of entire document
- `--position` - Extract from `start`, `middle`, or `end` (default: middle)
- `--max-sources N` - Maximum sources to check (default: 30)
- `--num-phrases N` - Number of key phrases to extract (default: auto-scale, 1 per page)
- `--use-apis` - Search academic APIs (CrossRef, arXiv, Semantic Scholar) in addition to web search
- `--use-local` - Compare with local reference files (.docx, .pdf, .txt) in `local_references` folder

The script will automatically search online, download sources, analyze similarities, and generate a report saved as `<filename>_plagiarism_report.txt` in the same directory as the input document.

## Installation

To use `plagiarism_checker.py`, you'll need to install the following Python libraries:

```
pip install python-docx PyMuPDF requests beautifulsoup4 scikit-learn nltk
```

The script will automatically download required NLTK data (punkt tokenizer and stopwords) on first run if not already present.

## Limitations

- Only detects textual similarities (no paraphrasing or semantic rewording detection)
- Only searches publicly accessible web content
- Does NOT access academic databases or paywalled content
- Search is rate-limited to avoid IP blocking
- Results depend on the quality and availability of online sources