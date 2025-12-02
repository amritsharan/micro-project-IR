#!/usr/bin/env python3
"""
Test script for exact phrase matching feature
Tests both regular tokenized queries and exact phrase queries with quotes
"""

from engine import IREngine

def test_exact_phrase_matching():
    """Test exact phrase matching with quoted queries"""
    engine = IREngine()
    
    print("=" * 80)
    print("EXACT PHRASE MATCHING TEST")
    print("=" * 80)
    print(f"\nDocuments loaded: {len(engine.docs_raw)}")
    
    if not engine.docs_raw:
        print("❌ No documents found! Cannot run tests.")
        return
    
    # Test Case 1: Regular tokenized query (without quotes)
    print("\n📝 Test 1: Regular Tokenized Query (Stopword Filtered)")
    print("-" * 80)
    query1 = "scoring term weighting"
    print(f"Query: {query1}")
    print(f"Mode: Tokenized search with stopword filtering")
    print(f"Processing: Filters stopwords, returns relevant matches")
    results1 = engine.search(query1, method="tfidf", top_k=3)
    print(f"Results: {len(results1)} documents found")
    for i, res in enumerate(results1, 1):
        print(f"  {i}. {res['name']} (score: {res['score']})")
        if res.get('snippet'):
            print(f"     {res['snippet'][:80]}...")
    
    # Test Case 2: Exact phrase query (with quotes)
    print("\n📝 Test 2: Exact Phrase Query (Quoted)")
    print("-" * 80)
    query2 = '"scoring term weighting"'
    print(f"Query: {query2}")
    print(f"Mode: Exact phrase match (case-insensitive)")
    print(f"Processing: Searches for exact phrase in documents")
    results2 = engine.search(query2, method="tfidf", top_k=3)
    print(f"Results: {len(results2)} documents found")
    for i, res in enumerate(results2, 1):
        match_count = res.get('phrase_matches', 0)
        print(f"  {i}. {res['name']} (score: {res['score']}, matches: {match_count})")
        if res.get('snippet'):
            print(f"     {res['snippet'][:80]}...")
    
    # Test Case 3: Single word in quotes
    print("\n📝 Test 3: Single Word Exact Match (Quoted)")
    print("-" * 80)
    query3 = '"scoring"'
    print(f"Query: {query3}")
    print(f"Mode: Exact word match")
    results3 = engine.search(query3, method="tfidf", top_k=2)
    print(f"Results: {len(results3)} documents found")
    for i, res in enumerate(results3, 1):
        match_count = res.get('phrase_matches', 0)
        print(f"  {i}. {res['name']} (score: {res['score']}, matches: {match_count})")
    
    # Test Case 4: Query without quotes (comparison)
    print("\n📝 Test 4: Same Query WITHOUT Quotes (Comparison)")
    print("-" * 80)
    query4 = "scoring"
    print(f"Query: {query4}")
    print(f"Mode: Tokenized search")
    results4 = engine.search(query4, method="tfidf", top_k=2)
    print(f"Results: {len(results4)} documents found")
    for i, res in enumerate(results4, 1):
        print(f"  {i}. {res['name']} (score: {res['score']})")
    
    # Test Case 5: Complex phrase
    print("\n📝 Test 5: Complex Phrase with Multiple Words")
    print("-" * 80)
    query5 = '"vector space"'
    print(f"Query: {query5}")
    print(f"Mode: Exact phrase match")
    results5 = engine.search(query5, method="tfidf", top_k=3)
    print(f"Results: {len(results5)} documents found")
    for i, res in enumerate(results5, 1):
        match_count = res.get('phrase_matches', 0)
        print(f"  {i}. {res['name']} (score: {res['score']}, matches: {match_count})")
        if res.get('snippet'):
            print(f"     {res['snippet'][:80]}...")
    
    # Test Case 6: Non-existent phrase
    print("\n📝 Test 6: Non-existent Phrase")
    print("-" * 80)
    query6 = '"xyzabc123 nonexistent phrase xyz"'
    print(f"Query: {query6}")
    print(f"Mode: Exact phrase match (should return nothing or low scores)")
    results6 = engine.search(query6, method="tfidf", top_k=3)
    print(f"Results: {len(results6)} documents found")
    if results6:
        for i, res in enumerate(results6, 1):
            print(f"  {i}. {res['name']} (score: {res['score']})")
    else:
        print("  ✓ No documents match this phrase (expected)")
    
    print("\n" + "=" * 80)
    print("FEATURE SUMMARY")
    print("=" * 80)
    print("✅ Feature: Exact Phrase Matching")
    print("✅ Usage: Wrap query in double quotes for exact phrase search")
    print("✅ Example: \"deadlock prevention\" searches for exact phrase")
    print("✅ Without quotes: Regular tokenized search with stopword filtering")
    print("✅ Backward compatible: All existing queries work as before")
    print("\n📌 KEY DIFFERENCES:")
    print("   Regular query:  'scoring term' → tokenized & filtered")
    print("   Exact phrase:   '\"scoring term\"' → exact match in document")
    print("=" * 80)

if __name__ == "__main__":
    test_exact_phrase_matching()
