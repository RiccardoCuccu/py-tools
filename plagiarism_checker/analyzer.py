"""
Similarity Analyzer Module - STEP 5

Calculates similarity between documents and generates detailed reports.
"""

import sys
from pathlib import Path
from datetime import datetime

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    from nltk.tokenize import sent_tokenize
except ImportError as e:
    print(f"Error: Missing required library - {e}")
    print("pip install scikit-learn nltk")
    sys.exit(1)


class SimilarityAnalyzer:
    def __init__(self, doc_path):
        """Initialize similarity analyzer"""
        self.doc_path = Path(doc_path)
        # Report should be saved in script directory, not document directory
        self.script_dir = Path(__file__).resolve().parent
    
    def analyze_sources(self, doc_text, sources):
        """Analyze all sources against the document for similarity"""
        print(f"\n[5/5] Analyzing similarity with downloaded sources...")
        results = []
        
        for i, source in enumerate(sources, 1):
            print(f"  Analyzing source {i}/{len(sources)}...")
            
            # Calculate overall document similarity
            overall_similarity = self._calculate_similarity(doc_text, source['content'])
            
            # Find specific matching text segments
            matches = self._find_matching_segments(doc_text, source['content'])
            
            # Include source if it has similarity >= 1% or has matching segments
            if overall_similarity >= 0.01 or len(matches) > 0:
                result = {
                    'overall_similarity': overall_similarity,
                    'matching_segments': len(matches),
                    'matches': matches[:5],
                    'is_local': source.get('is_local', False),
                    'url': source.get('file_path' if source.get('is_local', False) else 'url', ''),
                    'title': source.get('file_name' if source.get('is_local', False) else 'title', 'Unknown')
                }
                
                # Add local-specific fields
                if result['is_local']:
                    result['file_name'] = source.get('file_name', 'Unknown')
                    result['file_path'] = source.get('file_path', 'N/A')

                results.append(result)
        
        # Sort by similarity score
        results.sort(key=lambda x: x['overall_similarity'], reverse=True)
        
        print(f"✓ Analysis complete")
        return results
    
    def _calculate_similarity(self, text1, text2):
        """Calculate cosine similarity between two texts using TF-IDF"""
        try:
            vectorizer = TfidfVectorizer(stop_words='english', max_features=1000)
            tfidf_matrix = vectorizer.fit_transform([text1, text2])
            similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]  # type: ignore[index]
            return float(similarity)
        except (ValueError, RuntimeError) as e:
            print(f"    Warning: Similarity calculation failed: {e}")
            return 0.0
    
    def _find_matching_segments(self, doc_text, source_text, threshold=0.7):
        """Find matching text segments using batch TF-IDF computation"""
        doc_sentences = [s for s in sent_tokenize(doc_text) if len(s.split()) >= 5]
        source_sentences = [s for s in sent_tokenize(source_text) if len(s.split()) >= 5]
        
        if not doc_sentences or not source_sentences:
            return []
        
        try:
            # Batch compute similarities for all sentence pairs
            vectorizer = TfidfVectorizer(stop_words='english', max_features=500)
            all_sentences = doc_sentences + source_sentences
            tfidf_matrix = vectorizer.fit_transform(all_sentences)
            
            doc_matrix = tfidf_matrix[:len(doc_sentences)]  # type: ignore[index]
            source_matrix = tfidf_matrix[len(doc_sentences):]  # type: ignore[index]
            
            # Compute similarity matrix for all pairs at once
            similarity_matrix = cosine_similarity(doc_matrix, source_matrix)  # type: ignore[arg-type]
            
            matches = []
            for i, doc_sent in enumerate(doc_sentences):
                max_idx = int(similarity_matrix[i].argmax())
                max_sim = float(similarity_matrix[i, max_idx])
                if max_sim >= threshold:
                    matches.append({
                        'doc_text': doc_sent,
                        'source_text': source_sentences[max_idx],
                        'similarity': max_sim
                    })
            
            return matches
        except (ValueError, RuntimeError) as e:
            print(f"    Warning: Segment matching failed: {e}")
            return []
    
    def generate_report(self, results, doc_text, failed_sources=None, num_local_sources=0):
        """Generate and save detailed plagiarism report"""
        local_results = [r for r in results if r.get('is_local', False)]
        online_results = [r for r in results if not r.get('is_local', False)]

        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("PLAGIARISM CHECK REPORT")
        report_lines.append("=" * 80)
        report_lines.append(f"Document: {self.doc_path.name}")
        report_lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"Document length: {len(doc_text)} characters")
        report_lines.append(f"Sources analyzed: {len(results)} ({len(local_results)} local, {len(online_results)} online)")
        if failed_sources:
            report_lines.append(f"Online sources failed to download: {len(failed_sources)}")
        report_lines.append("=" * 80)
        
        if not results:
            report_lines.append("\n✓ NO SIGNIFICANT MATCHES FOUND")
            report_lines.append("\nThe document appears to be original or no similar sources were found online.")
        else:
            max_similarity = results[0]['overall_similarity'] if results else 0.0
            total_segments = sum(r['matching_segments'] for r in results) if results else 0
            
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

            # Local sources section
            if local_results:
                report_lines.append("\n" + "-" * 80)
                report_lines.append("LOCAL REFERENCE FILES")
                report_lines.append("-" * 80)

                for i, result in enumerate(local_results, 1):
                    report_lines.append(f"\nLOCAL SOURCE #{i}")
                    report_lines.append(f"  File: {result.get('file_name', 'Unknown')}")
                    report_lines.append(f"  Path: {result.get('file_path', 'N/A')}")
                    report_lines.append(f"  Overall Similarity: {result['overall_similarity']*100:.1f}%")
                    report_lines.append(f"  Matching Segments: {result['matching_segments']}")

                    if result['matches']:
                        report_lines.append(f"\n  Sample Matches:")
                        for j, match in enumerate(result['matches'][:3], 1):
                            report_lines.append(f"\n  Match {j} (Similarity: {match['similarity']*100:.1f}%):")
                            report_lines.append(f"    Document: \"{match['doc_text'][:150]}...\"")
                            report_lines.append(f"    Source:   \"{match['source_text'][:150]}...\"")

                    report_lines.append("\n" + "-" * 80)

            # Online sources section
            if online_results:
                report_lines.append("\n" + "-" * 80)
                report_lines.append("ONLINE SOURCES")
                report_lines.append("-" * 80)

                for i, result in enumerate(online_results, 1):
                    report_lines.append(f"\nONLINE SOURCE #{i}")
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

        # Failed downloads section
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

        # Limitations
        report_lines.append("\n" + "=" * 80)
        report_lines.append("LIMITATIONS")
        report_lines.append("=" * 80)
        report_lines.append("- This tool only detects textual similarities")
        report_lines.append("- Does NOT detect paraphrasing or semantic rewording")
        report_lines.append("- Only searches publicly accessible web content")
        report_lines.append("- Does NOT access academic databases or paywalled sources")
        report_lines.append("=" * 80)
        
        report_text = '\n'.join(report_lines)
        
        # Save report in script directory with document name
        report_file = self.script_dir / f"{self.doc_path.stem}_plagiarism_report.txt"
        report_file.write_text(report_text, encoding='utf-8')
        
        # Print to console
        print("\n" + report_text)
        print(f"\n✓ Report saved to: {report_file}")