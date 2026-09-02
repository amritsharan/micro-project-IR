#!/usr/bin/env python3
"""
Test script for Semantic Hybrid Search feature (BM25 + Vector Embeddings)
"""

import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from engine import IREngine

def test_hybrid_search():
    print("=" * 80)
    print("HYBRID SEMANTIC SEARCH TEST")
    print("=" * 80)

    engine = IREngine()
    print(f"\nDocuments loaded: {len(engine.docs_raw)}")
    
    if not engine.docs_raw:
        print("❌ No documents found to test.")
        return

    # Test query 1: Conceptual search (searching concept vs exact words)
    query1 = "resource allocation and CPU management"
    print(f"\n📝 Test 1: Conceptual Search with Hybrid (BM25 + Semantic)")
    print("-" * 80)
    print(f"Query: '{query1}'")
    
    results_tfidf = engine.search(query1, method="tfidf", top_k=3)
    results_bm25 = engine.search(query1, method="bm25", top_k=3)
    results_hybrid = engine.search(query1, method="hybrid", top_k=3)

    print("\n[TF-IDF Results]")
    for i, r in enumerate(results_tfidf, 1):
        print(f"  {i}. {r['name']} (score: {r['score']})")

    print("\n[BM25 Results]")
    for i, r in enumerate(results_bm25, 1):
        print(f"  {i}. {r['name']} (score: {r['score']})")

    print("\n[Hybrid (BM25 + Semantic) Results]")
    for i, r in enumerate(results_hybrid, 1):
        print(f"  {i}. {r['name']} (RRF score: {r['score']})")

    print("\n" + "=" * 80)
    print("HYBRID SEARCH TEST SUMMARY")
    print("=" * 80)
    print("✅ Hybrid Search Execution: Success")
    print(f"✅ Returned {len(results_hybrid)} hybrid ranked results")
    print("=" * 80)

if __name__ == "__main__":
    test_hybrid_search()
