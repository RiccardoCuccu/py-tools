"""
Phrase Selection Module - STEP 2

Extracts key phrases from text using TF-IDF scoring for optimal search queries.
"""

import sys

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    import nltk
    from nltk.corpus import stopwords
    from nltk.tokenize import sent_tokenize
except ImportError as e:
    print(f"Error: Missing required library - {e}")
    print("pip install scikit-learn nltk")
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


class PhraseSelector:
    def __init__(self, min_phrase_words=8, num_phrases=None):
        """Initialize phrase selector with configuration"""
        self.min_phrase_words = min_phrase_words
        self.num_phrases = num_phrases
        self.stop_words = set(stopwords.words('english'))
    
    def extract_key_phrases(self, text):
        """Extract key phrases from text for searching using TF-IDF scoring"""
        print(f"\n[2/5] Extracting key phrases for search...")

        # Tokenize text into sentences
        sentences = sent_tokenize(text)
        
        # Filter sentences based on length and meaningful content
        filtered_sentences = []
        for sent in sentences:
            words = sent.split()
            if self.min_phrase_words <= len(words) <= 20:
                meaningful_words = [w for w in words if w.lower() not in self.stop_words]
                if len(meaningful_words) >= self.min_phrase_words / 2:
                    filtered_sentences.append(sent)

        if not filtered_sentences:
            print("  Warning: No suitable sentences found, using original text")
            return [text[:200]]

        # Determine number of phrases to extract
        if self.num_phrases is not None:
            if self.num_phrases == 0:
                # Extract ALL filtered sentences
                num_phrases = len(filtered_sentences)
                print(f"\n⚠ WARNING: Extracting ALL relevant phrases ({num_phrases} phrases)")
                print("  - This will perform many online searches and significantly increase processing time")
                print("  - Each phrase requires a web search with rate limiting delays")
                print(f"  - Estimated time: {num_phrases * 2} seconds just for searching")
                print("  - Consider using a specific number (e.g., --num-phrases 20) for faster results")
                print()
                
                # Import confirm_continue from main
                from main import confirm_continue
                confirm_continue()
                print(f"  Target: ALL relevant phrases ({num_phrases} phrases)")
            else:
                num_phrases = self.num_phrases
                print(f"  Target: {num_phrases} key phrases")
        else:
            # Auto-scale: approximately 1 phrase per page
            estimated_pages = max(1, len(text) // 3000)
            num_phrases = max(5, min(estimated_pages, 20))
            print(f"  Target: {num_phrases} key phrases")

        # Select phrases using TF-IDF if we have more candidates than needed
        if len(filtered_sentences) <= num_phrases:
            phrases = filtered_sentences
        else:
            try:
                # Use TF-IDF to find most distinctive sentences
                vectorizer = TfidfVectorizer(stop_words='english', max_features=100)
                tfidf_matrix = vectorizer.fit_transform(filtered_sentences)

                # Calculate importance score for each sentence and get top N
                scores = tfidf_matrix.sum(axis=1).A1  # type: ignore[attr-defined]
                top_indices = scores.argsort()[-num_phrases:][::-1]
                
                # Maintain document order
                phrases = [filtered_sentences[i] for i in sorted(top_indices)]

            except (ValueError, RuntimeError) as e:
                print(f"  Warning: TF-IDF scoring failed ({str(e)}), using uniform distribution")
                # Fallback: uniform distribution
                step = len(filtered_sentences) // num_phrases
                phrases = [filtered_sentences[i * step] for i in range(num_phrases)]

        print(f"✓ Selected {len(phrases)} key phrases for searching")
        return phrases