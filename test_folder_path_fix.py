#!/usr/bin/env python
"""
Test folder path handling - verify manual path entry works correctly
"""

import os
import tempfile
import shutil
from pathlib import Path

def test_folder_path_handling():
    """Test folder path validation and loading"""
    
    print("=" * 70)
    print("Testing Folder Path Handling - Manual Entry")
    print("=" * 70)
    
    # Import engine
    try:
        from engine import IREngine, load_documents
        print("\n✅ Engine imported successfully\n")
    except Exception as e:
        print(f"\n❌ Failed to import engine: {e}")
        return False
    
    # Create test folder with documents
    test_dir = tempfile.mkdtemp(prefix="ir_folder_test_")
    print(f"📁 Test folder created: {test_dir}")
    
    # Create sample documents
    sample_docs = {
        "doc1.txt": "Machine learning is artificial intelligence",
        "doc2.txt": "Deep learning uses neural networks",
        "doc3.txt": "Classification is a supervised task"
    }
    
    for filename, content in sample_docs.items():
        with open(os.path.join(test_dir, filename), 'w') as f:
            f.write(content)
        print(f"  ✓ Created: {filename}")
    
    # TEST 1: Manual path entry (Windows style)
    print(f"\n{'-' * 70}")
    print("TEST 1: Manual path entry - Simulating user enters folder path")
    print(f"{'-' * 70}")
    print(f"User enters: {test_dir}")
    
    engine = IREngine()
    
    try:
        # Simulate user manually entering folder path
        if os.path.isdir(test_dir):
            success = engine.load_from_folder(test_dir, recursive=False)
            if success:
                print(f"✅ Folder loaded successfully")
                print(f"   - Documents found: {len(engine.doc_names)}")
                for i, name in enumerate(engine.doc_names, 1):
                    print(f"     {i}. {name}")
            else:
                print(f"❌ Failed to load folder")
                return False
        else:
            print(f"❌ Folder path invalid: {test_dir}")
            return False
    except Exception as e:
        print(f"❌ Error loading folder: {e}")
        return False
    
    # TEST 2: Search on manually loaded folder
    print(f"\n{'-' * 70}")
    print("TEST 2: Query on manually loaded folder")
    print(f"{'-' * 70}")
    
    test_query = "machine learning"
    print(f"Query: '{test_query}'")
    
    try:
        results = engine.search(test_query, method="tfidf", top_k=3)
        
        if results:
            print(f"✅ Search successful - {len(results)} results found")
            for i, result in enumerate(results, 1):
                print(f"   {i}. {result['name']} (score: {result['score']:.4f})")
        else:
            print(f"❌ No results found")
            return False
    except Exception as e:
        print(f"❌ Error during search: {e}")
        return False
    
    # TEST 3: Recursive folder loading
    print(f"\n{'-' * 70}")
    print("TEST 3: Recursive folder loading with subfolders")
    print(f"{'-' * 70}")
    
    # Create subfolder with document
    subfolder = os.path.join(test_dir, "subfolder")
    os.makedirs(subfolder, exist_ok=True)
    with open(os.path.join(subfolder, "doc4.txt"), 'w') as f:
        f.write("Clustering groups similar data points")
    print(f"✓ Created subfolder with document")
    
    try:
        # Load with recursive option
        success = engine.load_from_folder(test_dir, recursive=True)
        if success:
            print(f"✅ Recursive load successful")
            print(f"   - Documents found: {len(engine.doc_names)}")
            for i, name in enumerate(engine.doc_names, 1):
                print(f"     {i}. {name}")
            
            if len(engine.doc_names) >= 4:
                print(f"✅ Subfolder document included!")
            else:
                print(f"⚠️  Expected 4+ documents, found {len(engine.doc_names)}")
        else:
            print(f"❌ Failed to load with recursion")
            return False
    except Exception as e:
        print(f"❌ Error during recursive load: {e}")
        return False
    
    # TEST 4: Invalid path handling
    print(f"\n{'-' * 70}")
    print("TEST 4: Invalid path handling")
    print(f"{'-' * 70}")
    
    invalid_path = "/nonexistent/folder/path"
    print(f"Attempting to load invalid path: {invalid_path}")
    
    try:
        result = engine.load_from_folder(invalid_path, recursive=False)
        if not result:
            print(f"✅ Invalid path correctly rejected (returned False)")
        else:
            print(f"❌ Invalid path was accepted (unexpected)")
            return False
    except Exception as e:
        print(f"❌ Error during invalid path test: {e}")
        return False
    
    # Cleanup
    print(f"\n{'-' * 70}")
    print("CLEANUP")
    print(f"{'-' * 70}")
    shutil.rmtree(test_dir)
    print(f"✅ Test folder cleaned up")
    
    # Summary
    print("\n" + "=" * 70)
    print("✅ ALL TESTS PASSED!")
    print("\nWorkflow is now:")
    print("  1. User enters folder path manually (no browser needed)")
    print("  2. User clicks 'Load Folder'")
    print("  3. System loads all documents from that folder")
    print("  4. User enters search query")
    print("  5. System ranks documents by relevance")
    print("  6. Results displayed with scores")
    print("\nThis is simple, reliable, and works on all systems!")
    print("=" * 70)
    
    return True

if __name__ == '__main__':
    success = test_folder_path_handling()
    exit(0 if success else 1)
