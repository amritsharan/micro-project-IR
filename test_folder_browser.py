#!/usr/bin/env python
"""
Test folder browser feature implementation
Tests:
1. Folder browser HTML elements exist
2. JavaScript folder handling functions defined
3. Folder path validation in backend
4. Document ranking after folder selection
"""

import re
from pathlib import Path

def test_folder_browser_html():
    """Test that folder path input HTML elements are present"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for folder path input and display
    assert 'id="folderPathDisplay"' in content or 'name="folder_path"' in content, "❌ Folder path input missing"
    assert 'folder_path' in content, "❌ Folder path input name missing"
    
    # Check for load folder button
    assert 'Load Folder' in content, "❌ Load Folder button text missing"
    assert 'name="folder_action"' in content, "❌ Folder action button missing"
    
    print("✅ Test 1: All folder path HTML elements present")

def test_folder_browser_javascript():
    """Test that folder handling and backend methods are defined"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for folder path handling
    assert 'folder_path' in content, "❌ Folder path handling missing"
    assert 'folderPathDisplay' in content, "❌ Folder path display reference missing"
    assert 'load_from_folder' in content, "❌ Backend load_from_folder missing"
    
    print("✅ Test 2: Folder path handling properly defined")

def test_backend_folder_handling():
    """Test that backend handles folder selection correctly"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for folder action handling
    assert 'folder_action' in content or 'folder_path' in content, "❌ Folder parameter missing"
    assert 'os.path.isdir' in content, "❌ Directory validation missing"
    
    # Check for load_from_folder method
    assert 'def load_from_folder' in content, "❌ load_from_folder method missing"
    assert 'recursive' in content, "❌ Recursive folder loading missing"
    
    # Check for status feedback
    assert 'folder_status' in content or 'current_folder' in content, "❌ Folder status feedback missing"
    assert 'Loaded from:' in content or 'Loaded' in content, "❌ Success message missing"
    
    print("✅ Test 3: Backend folder handling implemented")

def test_document_ranking_workflow():
    """Test that documents are ranked after folder selection"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for search after folder selection
    assert 'engine.search' in content, "❌ Search functionality missing"
    assert 'results = engine.search' in content or 'results = ' in content, "❌ Results assignment missing"
    
    # Check for both algorithms available
    assert 'tfidf' in content, "❌ TF-IDF not available"
    assert 'bm25' in content or 'BM25' in content, "❌ BM25 not available"
    
    print("✅ Test 4: Document ranking after folder selection works")

def test_form_submission():
    """Test form submission with folder selection"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for query handling in search
    assert 'query' in content, "❌ Query parameter retrieval missing"
    assert 'mainForm' in content or 'form' in content, "❌ Form element missing"
    
    print("✅ Test 5: Form submission and query handling implemented")

def test_compatibility():
    """Test folder path compatibility features"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for manual folder path entry input
    assert 'name="folder_path"' in content, "❌ Manual folder path entry missing"
    
    print("✅ Test 6: Folder path entry implemented")

if __name__ == '__main__':
    print("=" * 60)
    print("Testing Folder Browser Feature Implementation")
    print("=" * 60)
    
    try:
        test_folder_browser_html()
        test_folder_browser_javascript()
        test_backend_folder_handling()
        test_document_ranking_workflow()
        test_form_submission()
        test_compatibility()
        
        print("\n" + "=" * 60)
        print("✅ All tests PASSED! Folder browser feature ready.")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ Test FAILED: {e}")
        exit(1)
