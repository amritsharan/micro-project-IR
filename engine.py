# engine.py — DocVista Entry Point & Backward Compatibility Wrapper
# Run: python engine.py

import os
from app import create_app, DOCS_FOLDER
from app.ir_engine import IREngine
from app.parsers import (
    load_documents,
    extract_text_from_pdf,
    extract_text_from_docx,
    extract_text_from_txt,
    preprocess,
    normalize_for_index,
    filter_stopwords,
    extract_snippet,
    extract_snippet_phrase,
    ENGLISH_STOPWORDS
)
from app.bm25 import BM25Simple
from app.pdf_exporter import highlight_pdf_bytes, create_search_report_pdf
from app.routes import engine

app = create_app()

if __name__ == "__main__":
    print("Loading documents from:", os.path.abspath(DOCS_FOLDER))
    print("Open http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
