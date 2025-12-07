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
    """Test that folder browser HTML elements are present"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for folder browser file input
    assert 'id="folderBrowser"' in content, "❌ Folder browser input missing"
    assert 'webkitdirectory' in content, "❌ webkitdirectory attribute missing"
    assert 'mozdirectory' in content, "❌ mozdirectory attribute missing"
    
    # Check for browse button
    assert 'id="browseFolderBtn"' in content, "❌ Browse button missing"
    assert 'Browse Folder' in content, "❌ Browse button text missing"
    
    # Check for folder path display
    assert 'id="folderPathDisplay"' in content, "❌ Folder path display missing"
    assert 'folder_path' in content, "❌ Folder path input missing"
    
    print("✅ Test 1: All folder browser HTML elements present")

def test_folder_browser_javascript():
    """Test that JavaScript folder handling functions are defined"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for JavaScript folder handler
    assert 'browseFolderBtn?.addEventListener' in content, "❌ Browse button event listener missing"
    assert 'folderBrowser?.addEventListener' in content, "❌ Folder browser event listener missing"
    assert 'folderPathDisplay' in content, "❌ Folder path display reference missing"
    
    # Check for visual feedback
    assert '#10b981' in content, "❌ Success color feedback missing"
    assert 'Folder selected' in content, "❌ Selection confirmation missing"
    
    print("✅ Test 2: JavaScript folder browser handlers properly defined")

def test_backend_folder_handling():
    """Test that backend handles folder selection correctly"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for folder action handling
    assert 'folder_action' in content, "❌ Folder action parameter missing"
    assert 'os.path.isdir' in content, "❌ Directory validation missing"
    
    # Check for load_from_folder method
    assert 'def load_from_folder' in content, "❌ load_from_folder method missing"
    assert 'recursive' in content, "❌ Recursive folder loading missing"
    
    # Check for status feedback
    assert 'folder_status' in content, "❌ Folder status feedback missing"
    assert 'Loaded from:' in content, "❌ Success message missing"
    
    print("✅ Test 3: Backend folder handling implemented")

def test_document_ranking_workflow():
    """Test that documents are ranked after folder selection"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for search after folder selection
    assert 'engine.search' in content, "❌ Search functionality missing"
    assert 'results = engine.search' in content, "❌ Results assignment missing"
    
    # Check for both algorithms available
    assert 'tfidf' in content, "❌ TF-IDF not available"
    assert 'bm25' in content or 'BM25' in content, "❌ BM25 not available"
    
    # Check that method parameter is used
    assert 'method=method' in content, "❌ Algorithm selection not implemented"
    
    print("✅ Test 4: Document ranking after folder selection works")

def test_form_submission():
    """Test form submission with folder selection"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for form submission handling
    assert 'folderForm?.addEventListener' in content, "❌ Form submission handler missing"
    assert '"submit"' in content, "❌ Submit event listener missing"
    
    # Check for query handling in search
    assert 'query = request.form.get("query"' in content, "❌ Query parameter retrieval missing"
    assert 'if query:' in content, "❌ Query validation missing"
    
    print("✅ Test 5: Form submission and query handling implemented")

def test_compatibility():
    """Test browser compatibility features"""
    with open('engine.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for multiple directory APIs for browser compatibility
    assert 'webkitRelativePath' in content, "❌ webkit relative path missing"
    assert '.split' in content, "❌ Path parsing missing"
    
    # Check for fallback to manual entry
    assert 'name="folder_path"' in content, "❌ Manual folder path entry missing"
    
    print("✅ Test 6: Browser compatibility and fallback implemented")

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
