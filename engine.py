# engine.py — DocVista (Material + Professional UI)
# Run: python engine.py
# Requirements:
# pip install flask python-docx PyPDF2 pymupdf fpdf2 scikit-learn numpy

import os
import io
import re
import string
import time
import unicodedata
from math import log
from urllib.parse import quote_plus, unquote_plus
from pathlib import Path

from flask import Flask, request, render_template_string, send_file, redirect, url_for, jsonify
from werkzeug.utils import secure_filename

import docx
import PyPDF2
import fitz  # PyMuPDF
import numpy as np
from fpdf import FPDF
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ----------------------------
# Config
# ----------------------------
DOCS_FOLDER = "documents"
ALLOWED_EXT = (".txt", ".pdf", ".docx")
os.makedirs(DOCS_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # 300 MB

# ----------------------------
# Utilities: extraction & preprocess
# ----------------------------
def extract_text_from_pdf(path):
    out = ""
    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for p in reader.pages:
                try:
                    txt = p.extract_text()
                except Exception:
                    txt = None
                if txt:
                    out += txt + " "
    except Exception:
        # fallback to PyMuPDF
        try:
            doc = fitz.open(path)
            for page in doc:
                out += page.get_text("text") + " "
            doc.close()
        except Exception:
            return ""
    return out

def extract_text_from_docx(path):
    try:
        doc = docx.Document(path)
        return " ".join([p.text for p in doc.paragraphs if p.text])
    except Exception:
        return ""

def extract_text_from_txt(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def preprocess(text):
    if text is None:
        return ""
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def normalize_for_index(text):
    text = text.lower()
    return text.translate(str.maketrans("", "", string.punctuation))

# English stopwords for filtering
ENGLISH_STOPWORDS = {
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and', 'any', 'are', 
    'as', 'at', 'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but', 
    'by', 'can', 'could', 'did', 'do', 'does', 'doing', 'down', 'during', 'each', 'few', 'for', 
    'from', 'further', 'had', 'has', 'have', 'having', 'he', 'her', 'here', 'hers', 'herself', 
    'him', 'himself', 'his', 'how', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'itself', 'just', 
    'me', 'might', 'more', 'most', 'my', 'myself', 'no', 'nor', 'not', 'of', 'off', 'on', 'once', 
    'only', 'or', 'other', 'our', 'ours', 'ourselves', 'out', 'over', 'own', 'same', 'so', 'some', 
    'such', 'than', 'that', 'the', 'their', 'theirs', 'them', 'themselves', 'then', 'there', 
    'these', 'they', 'this', 'those', 'to', 'too', 'under', 'until', 'up', 'very', 'was', 'we', 
    'were', 'what', 'when', 'where', 'which', 'while', 'who', 'whom', 'why', 'will', 'with', 'you', 
    'your', 'yours', 'yourself', 'yourselves'
}

def filter_stopwords(tokens):
    """Remove stopwords from token list"""
    return [t for t in tokens if t and t not in ENGLISH_STOPWORDS]

# ----------------------------
# Load documents
# ----------------------------
def load_documents(folder=DOCS_FOLDER, recursive=False):
    """Load documents from a folder, optionally recursively"""
    docs_raw, names, paths = [], [], []
    os.makedirs(folder, exist_ok=True)
    
    if recursive:
        # Recursively walk through subdirectories
        for root, dirs, files in os.walk(folder):
            for fname in sorted(files):
                if not fname.lower().endswith(ALLOWED_EXT):
                    continue
                fp = os.path.join(root, fname)
                raw = ""
                if fname.lower().endswith(".pdf"):
                    raw = extract_text_from_pdf(fp)
                elif fname.lower().endswith(".docx"):
                    raw = extract_text_from_docx(fp)
                else:
                    raw = extract_text_from_txt(fp)
                raw = preprocess(raw)
                if raw and len(raw) > 10:
                    docs_raw.append(raw)
                    # Store relative path for display
                    rel_path = os.path.relpath(fp, folder)
                    names.append(f"{rel_path} ({os.path.getsize(fp)} bytes)")
                    paths.append(fp)
    else:
        # Only files in the direct folder
        for fname in sorted(os.listdir(folder)):
            if not fname.lower().endswith(ALLOWED_EXT):
                continue
            fp = os.path.join(folder, fname)
            if not os.path.isfile(fp):
                continue
            raw = ""
            if fname.lower().endswith(".pdf"):
                raw = extract_text_from_pdf(fp)
            elif fname.lower().endswith(".docx"):
                raw = extract_text_from_docx(fp)
            else:
                raw = extract_text_from_txt(fp)
            raw = preprocess(raw)
            if raw and len(raw) > 10:
                docs_raw.append(raw)
                names.append(fname)
                paths.append(fp)
    return docs_raw, names, paths

# ----------------------------
# BM25 simple implementation
# ----------------------------
class BM25Simple:
    def __init__(self, docs_tokens):
        self.docs_tokens = docs_tokens
        self.N = len(docs_tokens)
        self.avgdl = sum(len(d) for d in docs_tokens) / self.N if self.N else 0.0
        self.doc_freqs = []
        self.df = {}
        for doc in docs_tokens:
            freqs = {}
            for w in doc:
                freqs[w] = freqs.get(w, 0) + 1
            self.doc_freqs.append(freqs)
            for w in freqs.keys():
                self.df[w] = self.df.get(w, 0) + 1
        self.idf = {}
        for w, freq in self.df.items():
            self.idf[w] = log(1 + (self.N - freq + 0.5) / (freq + 0.5))
        self.k1 = 1.5
        self.b = 0.75

    def score(self, query_tokens):
        scores = [0.0] * self.N
        for q in query_tokens:
            if q not in self.idf:
                continue
            idf = self.idf[q]
            for i in range(self.N):
                tf = self.doc_freqs[i].get(q, 0)
                if tf == 0:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * (len(self.docs_tokens[i]) / self.avgdl))
                scores[i] += idf * (tf * (self.k1 + 1)) / denom
        return scores

# ----------------------------
# IR engine
# ----------------------------
class IREngine:
    def __init__(self):
        self.docs_raw, self.doc_names, self.doc_paths = load_documents(DOCS_FOLDER)
        self.current_folder = DOCS_FOLDER
        self.recursive = False
        self._build()

    def load_from_folder(self, folder_path, recursive=False):
        """Load documents from a specific folder"""
        if os.path.isdir(folder_path):
            self.current_folder = folder_path
            self.recursive = recursive
            self.docs_raw, self.doc_names, self.doc_paths = load_documents(folder_path, recursive=recursive)
            self._build()
            return True
        return False

    def _build(self):
        self.vectorizer = TfidfVectorizer(stop_words="english")
        try:
            if self.docs_raw:
                self.doc_vectors = self.vectorizer.fit_transform(self.docs_raw)
            else:
                self.doc_vectors = None
        except Exception:
            self.doc_vectors = None
        self.docs_tokens = [normalize_for_index(d).split() for d in self.docs_raw]
        self.bm25 = BM25Simple(self.docs_tokens) if self.docs_tokens else None

    def refresh(self):
        self.docs_raw, self.doc_names, self.doc_paths = load_documents(self.current_folder, recursive=self.recursive)
        self._build()

    def search(self, query, method="tfidf", top_k=10):
        # Check if query is enclosed in double quotes for exact phrase matching
        is_exact_phrase = query.strip().startswith('"') and query.strip().endswith('"')
        
        if is_exact_phrase:
            # Remove quotes and search for exact phrase
            phrase_query = query.strip()[1:-1]  # Remove leading and trailing quotes
            return self._search_exact_phrase(phrase_query, top_k)
        
        # Standard tokenized search with stopword filtering
        query_plain = preprocess(query)
        query_norm = normalize_for_index(query_plain)
        # Get raw tokens
        raw_tokens = [t for t in query_norm.split() if t]
        # Filter stopwords for better relevance
        q_tokens = filter_stopwords(raw_tokens)
        
        # If all tokens were stopwords, use raw tokens as fallback
        if not q_tokens:
            q_tokens = raw_tokens
        
        results = []
        if method.lower() == "bm25" and self.bm25:
            scores = self.bm25.score(q_tokens)
            ranked = np.argsort(scores)[::-1]
            for idx in ranked[:top_k]:
                if scores[idx] > 0:  # Only include results with non-zero scores
                    results.append((idx, float(scores[idx])))
        else:
            if self.doc_vectors is None:
                return []
            try:
                q_vec = self.vectorizer.transform([query_plain])
                sims = cosine_similarity(q_vec, self.doc_vectors)[0]
            except Exception:
                if self.bm25:
                    scores = self.bm25.score(q_tokens)
                    ranked = np.argsort(scores)[::-1]
                    for idx in ranked[:top_k]:
                        if scores[idx] > 0:
                            results.append((idx, float(scores[idx])))
                else:
                    return []
            else:
                ranked = np.argsort(sims)[::-1]
                for idx in ranked[:top_k]:
                    if sims[idx] > 0:  # Only include results with non-zero scores
                        results.append((idx, float(sims[idx])))
        
        enriched = []
        for idx, score in results:
            snippet = extract_snippet(self.docs_raw[idx], q_tokens)
            enriched.append({
                "index": idx,
                "name": self.doc_names[idx],
                "path": self.doc_paths[idx],
                "score": round(score, 4),
                "snippet": snippet
            })
        return enriched

    def _search_exact_phrase(self, phrase, top_k=10):
        """Search for exact phrase match in documents (case-insensitive)"""
        phrase_lower = phrase.lower()
        results = []
        
        for idx, doc in enumerate(self.docs_raw):
            doc_lower = doc.lower()
            if phrase_lower in doc_lower:
                # Count occurrences for scoring
                count = doc_lower.count(phrase_lower)
                # Score based on position and frequency
                first_pos = doc_lower.find(phrase_lower)
                # Earlier position = higher score, more occurrences = higher score
                position_score = 1.0 - (first_pos / max(len(doc), 1000)) * 0.5
                frequency_score = min(count / 10.0, 1.0)  # Cap at 10 occurrences
                score = (position_score * 0.4 + frequency_score * 0.6)
                results.append((idx, score, count))
        
        # Sort by score (highest first)
        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:top_k]
        
        enriched = []
        for idx, score, count in results:
            snippet = extract_snippet_phrase(self.docs_raw[idx], phrase)
            enriched.append({
                "index": idx,
                "name": self.doc_names[idx],
                "path": self.doc_paths[idx],
                "score": round(score, 4),
                "snippet": snippet,
                "phrase_matches": count
            })
        return enriched

    def top_keywords(self, doc_id, top_n=10):
        if self.doc_vectors is None:
            return []
        if doc_id < 0 or doc_id >= self.doc_vectors.shape[0]:
            return []
        try:
            features = self.vectorizer.get_feature_names_out()
        except Exception:
            features = self.vectorizer.get_feature_names()
        vec = self.doc_vectors[doc_id]
        if hasattr(vec, "toarray"):
            arr = np.asarray(vec.toarray()).ravel()
        else:
            try:
                arr = np.asarray(vec.todense()).ravel()
            except Exception:
                return []
        if arr.sum() == 0:
            return []
        inds = np.argsort(arr)[::-1][:top_n]
        kws = []
        for i in inds:
            if arr[i] > 0:
                kws.append(f"{features[i]} ({arr[i]:.4f})")
        return kws

# ----------------------------
# Snippet extraction
# ----------------------------
def extract_snippet(doc_text, query_tokens, window=240):
    if not doc_text:
        return ""
    lower = doc_text.lower()
    best_pos = -1
    for token in query_tokens:
        if not token:
            continue
        pos = lower.find(token)
        if pos != -1:
            best_pos = pos
            break
    if best_pos == -1:
        snippet = (doc_text[:window] + "...") if len(doc_text) > window else doc_text
    else:
        start = max(0, best_pos - window // 2)
        end = min(len(doc_text), start + window)
        snippet = doc_text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(doc_text):
            snippet = snippet + "..."
    for t in set(query_tokens):
        if not t:
            continue
        esc = re.escape(t)
        snippet = re.sub(f"(?i)({esc})", r"<mark>\1</mark>", snippet)
    return snippet

def extract_snippet_phrase(doc_text, phrase, window=240):
    """Extract snippet for exact phrase match (case-insensitive)"""
    if not doc_text or not phrase:
        return ""
    lower = doc_text.lower()
    phrase_lower = phrase.lower()
    best_pos = lower.find(phrase_lower)
    
    if best_pos == -1:
        snippet = (doc_text[:window] + "...") if len(doc_text) > window else doc_text
    else:
        start = max(0, best_pos - window // 2)
        end = min(len(doc_text), start + window)
        snippet = doc_text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(doc_text):
            snippet = snippet + "..."
    
    # Highlight exact phrase
    esc = re.escape(phrase)
    snippet = re.sub(f"(?i)({esc})", r"<mark>\1</mark>", snippet)
    return snippet

# ----------------------------
# PDF Highlighting (PyMuPDF)
# ----------------------------
def highlight_pdf_bytes(original_path, query_terms):
    try:
        doc = fitz.open(original_path)
    except Exception:
        with open(original_path, "rb") as f:
            data = f.read()
        doc = fitz.open(stream=data, filetype="pdf")
    query_terms = [t.lower() for t in query_terms if t]
    for page in doc:
        for term in query_terms:
            if not term.strip():
                continue
            try:
                rects = page.search_for(term, hit_max=500)
                for r in rects:
                    try:
                        annot = page.add_highlight_annot(r)
                        annot.update()
                    except Exception:
                        pass
            except Exception:
                pass
    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True)
    out.seek(0)
    doc.close()
    return out

# ----------------------------
# PDF Export helpers — robust against long tokens
# ----------------------------
def normalize_text_for_pdf(text):
    if text is None:
        return ""
    # Replace fancy unicode punctuation with ASCII equivalents
    replacements = {
        '\u2013': '-', '\u2014': '-', '\u2015': '-',
        '\u2212': '-', '\u2022': '*', '\u00A0': ' ',
        '\u200b': '',  # Zero-width space
        '\u200c': '',  # Zero-width non-joiner
        '\u200d': '',  # Zero-width joiner
        '\u200e': '',  # Left-to-right mark
        '\u200f': '',  # Right-to-left mark
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    # Remove ALL control characters except newline and tab
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in '\n\t')
    # Remove any remaining non-ASCII printable characters that cause issues
    text = "".join(ch if ord(ch) < 128 or ord(ch) >= 160 else '' for ch in text)
    return str(text).strip()

def safe_wrap_long_tokens(text, max_len=40):
    """
    Insert hard line breaks inside very long tokens.
    Avoids zero-width spaces which FPDF can't handle.
    """
    if not text:
        return ""
    # sanitize: remove problematic control characters
    text = text.replace("\t", " ").replace("\r", " ")
    text = ''.join(ch for ch in text if ord(ch) >= 32 or ch == '\n')
    words = text.split(" ")
    wrapped = []
    for w in words:
        if len(w) <= max_len:
            wrapped.append(w)
        else:
            # Hard break with space separator
            parts = [w[i:i+max_len] for i in range(0, len(w), max_len)]
            wrapped.extend(parts)
    return " ".join(wrapped)

def force_break_long_tokens(text, max_len=80):
    """
    Breaks tokens longer than max_len into hard chunks separated by spaces.
    This is last-resort to prevent FPDF from failing.
    """
    if not text:
        return ""
    # Remove problematic Unicode before breaking
    text = normalize_text_for_pdf(text)
    tokens = text.split()
    out = []
    for tkn in tokens:
        if len(tkn) > max_len:
            chunks = [tkn[i:i+max_len] for i in range(0, len(tkn), max_len)]
            out.extend(chunks)
        else:
            out.append(tkn)
    return " ".join(out)

def clean_line_for_pdf(line):
    if line is None:
        return ""
    # Convert to string and normalize
    line = str(line)
    line = line.replace("\t", " ").replace("\r", " ")
    
    # Remove all problematic Unicode characters
    problematic_chars = {
        '\u200b',  # Zero-width space
        '\u200c',  # Zero-width non-joiner
        '\u200d',  # Zero-width joiner
        '\u200e',  # Left-to-right mark
        '\u200f',  # Right-to-left mark
        '\ufeff',  # Zero-width no-break space
    }
    for char in problematic_chars:
        line = line.replace(char, '')
    
    # Keep only ASCII printable and common Latin extended (160-255)
    line = ''.join(ch for ch in line if (32 <= ord(ch) <= 126) or (160 <= ord(ch) <= 255) or ch in '\n')
    return line

def chunk_text_final(text, size):
    """break a string into final safe chunks"""
    if not text:
        return []
    text = str(text)
    return [text[i:i+size] for i in range(0, len(text), size)]

def create_search_report_pdf(query, method, results):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    # Try DejaVu for unicode; fallback to Arial
    font_candidates = ["fonts/DejaVuSans.ttf", "fonts/ttf/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"]
    base_font = "helvetica"  # Default to built-in font
    custom_font_loaded = False
    
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                pdf.add_font("DejaVu", "", fp, uni=True)
                base_font = "DejaVu"
                custom_font_loaded = True
                break
            except Exception:
                pass

    # ==================== TITLE ====================
    if custom_font_loaded:
        pdf.set_font(base_font, size=18)  # No bold for custom fonts
    else:
        pdf.set_font(base_font, "B", size=18)  # Bold works with built-in fonts
    pdf.cell(0, 10, "DocVista - Search Report", ln=True, align="C")
    pdf.ln(5)

    # ==================== SEARCH INFO ====================
    pdf.set_font(base_font, size=10)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(0, 6, f"Query: {clean_line_for_pdf(query)}", ln=True, fill=True)
    pdf.cell(0, 6, f"Method: {method.upper()}", ln=True, fill=True)
    pdf.cell(0, 6, f"Results: {len(results)} documents", ln=True, fill=True)
    pdf.cell(0, 6, f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}", ln=True, fill=True)
    pdf.ln(5)

    # ==================== TABLE HEADER ====================
    if custom_font_loaded:
        pdf.set_font(base_font, size=11)  # No bold for custom fonts
    else:
        pdf.set_font(base_font, "B", size=11)  # Bold works with built-in fonts
    pdf.set_fill_color(40, 40, 40)
    pdf.set_text_color(255, 255, 255)
    
    # Column widths: No. | Document Name | Score
    col_no = 12
    col_name = 130
    col_score = 38
    
    pdf.cell(col_no, 8, "#", border=1, fill=True, align="C")
    pdf.cell(col_name, 8, "Document Name", border=1, fill=True, align="L")
    pdf.cell(col_score, 8, "Score", border=1, fill=True, align="C")
    pdf.ln(8)

    # ==================== TABLE ROWS ====================
    pdf.set_font(base_font, size=10)
    pdf.set_text_color(0, 0, 0)
    
    for i, r in enumerate(results, start=1):
        # Alternate row background colors for readability
        fill = (i % 2 == 0)
        if fill:
            pdf.set_fill_color(240, 240, 240)
        else:
            pdf.set_fill_color(255, 255, 255)
        
        doc_name = clean_line_for_pdf(r['name'][:50])  # Truncate long names
        score_str = f"{r['score']:.4f}"
        
        pdf.cell(col_no, 8, str(i), border=1, fill=fill, align="C")
        pdf.cell(col_name, 8, doc_name, border=1, fill=fill, align="L")
        pdf.cell(col_score, 8, score_str, border=1, fill=fill, align="C")
        pdf.ln(8)

    # ==================== FOOTER ====================
    pdf.ln(5)
    if custom_font_loaded:
        pdf.set_font(base_font, size=9)  # No italic for custom fonts
    else:
        pdf.set_font(base_font, "I", size=9)  # Italic works with built-in fonts
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4, f"Ranking Method: {method.upper()} | Total Documents Indexed: {len(engine.doc_names)} | Page {pdf.page_no()}")

    # Build bytes safely
    pdf_bytes = pdf.output(dest='S')
    # pdf.output() already returns bytes, no need to encode
    if isinstance(pdf_bytes, str):
        pdf_bytes = pdf_bytes.encode('latin-1', 'replace')
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    return buf

# ----------------------------
# HTML template — Material + Professional
# Single-file template (render_template_string)
# ----------------------------
BASE_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>DocVista — Smart IR Engine</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
* {margin:0;padding:0;box-sizing:border-box;}
:root {
  --primary: #3956ff;
  --primary-dark: #1e3a8a;
  --secondary: #f59e0b;
  --success: #10b981;
  --danger: #ef4444;
  --light-bg: #f8fafc;
  --card-bg: #ffffff;
  --text-primary: #0f172a;
  --text-secondary: #64748b;
  --border-color: #e2e8f0;
  --shadow-sm: 0 2px 8px rgba(15, 23, 42, 0.08);
  --shadow-md: 0 4px 16px rgba(15, 23, 42, 0.12);
  --shadow-lg: 0 8px 24px rgba(15, 23, 42, 0.15);
}

[data-theme="dark"] {
  --light-bg: #0f172a;
  --card-bg: #1e293b;
  --text-primary: #f1f5f9;
  --text-secondary: #cbd5e1;
  --border-color: #334155;
}

html, body {
  background: var(--light-bg);
  color: var(--text-primary);
  transition: background-color 0.3s ease, color 0.3s ease;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
  line-height: 1.6;
}

body { padding: 24px 16px; }

.container-main {
  max-width: 1200px;
  margin: 0 auto;
}

/* ===== HEADER ===== */
.navbar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 32px;
  gap: 24px;
}

.navbar-brand-section {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
}

.logo-badge {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  background: linear-gradient(135deg, var(--primary), var(--primary-dark));
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 800;
  font-size: 24px;
  box-shadow: var(--shadow-md);
  transition: transform 0.3s ease;
}

.logo-badge:hover {
  transform: translateY(-4px);
}

.brand-info h1 {
  font-size: 28px;
  font-weight: 700;
  margin: 0;
  letter-spacing: -0.5px;
}

.brand-info p {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 4px 0 0;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.navbar-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.theme-toggle {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.theme-toggle:hover {
  background: var(--light-bg);
  border-color: var(--primary);
}

.btn-sm-header {
  padding: 8px 14px;
  font-size: 13px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: var(--card-bg);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.3s ease;
  text-decoration: none;
}

.btn-sm-header:hover {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}

/* ===== SEARCH CARD ===== */
.search-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--shadow-md);
  margin-bottom: 32px;
  transition: all 0.3s ease;
}

.search-card:hover {
  box-shadow: var(--shadow-lg);
}

.search-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 20px;
  color: var(--text-primary);
}

.search-form {
  display: grid;
  grid-template-columns: 1fr auto 100px 140px;
  gap: 12px;
  margin-bottom: 16px;
}

.form-input {
  background: var(--light-bg);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 15px;
  color: var(--text-primary);
  transition: all 0.3s ease;
}

.form-input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(57, 86, 255, 0.1);
}

.form-select {
  background: var(--light-bg) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%233956ff' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E") right 10px center;
  background-repeat: no-repeat;
  background-size: 20px;
  padding-right: 36px;
  appearance: none;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 14px;
  cursor: pointer;
  color: var(--text-primary);
}

.btn-search {
  background: linear-gradient(135deg, var(--primary), var(--primary-dark));
  color: white;
  border: none;
  border-radius: 10px;
  padding: 12px 24px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.btn-search:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(57, 86, 255, 0.3);
}

.upload-row {
  display: flex;
  gap: 8px;
  align-items: stretch;
}

.file-input-wrapper {
  position: relative;
  flex: 1;
}

.file-input-wrapper input {
  opacity: 0;
  position: absolute;
  width: 100%;
}

.file-input-label {
  background: var(--light-bg);
  border: 2px dashed var(--border-color);
  border-radius: 10px;
  padding: 12px 16px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-input-label:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-upload {
  background: var(--success);
  color: white;
  border: none;
  border-radius: 10px;
  padding: 12px 20px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
}

.btn-upload:hover {
  opacity: 0.9;
  transform: translateY(-2px);
}

.upload-hint {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 12px;
  padding: 8px;
  background: var(--light-bg);
  border-left: 3px solid var(--primary);
  border-radius: 4px;
}

.upload-hint code {
  background: var(--card-bg);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
}

/* ===== RESULTS SECTION ===== */
.results-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  gap: 16px;
}

.results-meta {
  display: flex;
  align-items: center;
  gap: 16px;
}

.query-badge {
  background: linear-gradient(135deg, rgba(57, 86, 255, 0.1), rgba(30, 58, 138, 0.05));
  border: 1px solid rgba(57, 86, 255, 0.2);
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 14px;
  color: var(--text-primary);
}

.query-badge strong {
  color: var(--primary);
}

.doc-count {
  font-size: 13px;
  color: var(--text-secondary);
  background: var(--light-bg);
  padding: 6px 12px;
  border-radius: 6px;
}

.btn-export-main {
  background: linear-gradient(135deg, var(--primary), var(--primary-dark));
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
}

.btn-export-main:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(57, 86, 255, 0.3);
}

/* ===== RESULT CARD ===== */
.result-item {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 20px;
  margin-bottom: 16px;
  display: grid;
  grid-template-columns: 1fr 240px;
  gap: 24px;
  transition: all 0.3s ease;
  animation: slideIn 0.4s ease forwards;
  opacity: 0;
}

.result-item:nth-child(1) { animation-delay: 0.05s; }
.result-item:nth-child(2) { animation-delay: 0.1s; }
.result-item:nth-child(3) { animation-delay: 0.15s; }
.result-item:nth-child(4) { animation-delay: 0.2s; }
.result-item:nth-child(5) { animation-delay: 0.25s; }
.result-item:nth-child(n+6) { animation-delay: 0.3s; }

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.result-item:hover {
  border-color: var(--primary);
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}

.result-content h3 {
  font-size: 18px;
  font-weight: 700;
  margin: 0 0 8px;
  color: var(--text-primary);
  word-break: break-word;
}

.result-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.score-badge {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.1), rgba(5, 150, 105, 0.05));
  border: 1px solid rgba(16, 185, 129, 0.2);
  padding: 4px 10px;
  border-radius: 6px;
  font-weight: 600;
  color: var(--success);
}

.snippet {
  color: var(--text-primary);
  margin: 12px 0;
  padding: 12px;
  background: var(--light-bg);
  border-left: 3px solid var(--primary);
  border-radius: 6px;
  font-size: 14px;
  line-height: 1.5;
  max-height: 80px;
  overflow: hidden;
}

.snippet mark {
  background: linear-gradient(120deg, rgba(245, 158, 11, 0.4), rgba(245, 158, 11, 0.2));
  padding: 2px 4px;
  border-radius: 3px;
  font-weight: 600;
}

.keywords-section {
  margin-top: 12px;
}

.view-kws-btn {
  color: var(--primary);
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.3s ease;
}

.view-kws-btn:hover {
  gap: 8px;
}

.keywords-box {
  margin-top: 8px;
  padding: 12px;
  background: linear-gradient(135deg, rgba(57, 86, 255, 0.05), rgba(30, 58, 138, 0.03));
  border: 1px solid rgba(57, 86, 255, 0.1);
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
}

.keyword-item {
  display: inline-block;
  background: var(--card-bg);
  padding: 4px 10px;
  border-radius: 6px;
  margin: 4px 4px 4px 0;
  border: 1px solid var(--border-color);
  color: var(--primary);
  font-weight: 500;
}

/* Result Actions */
.result-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  justify-content: flex-start;
}

.btn-action {
  padding: 10px 14px;
  border: 1px solid var(--border-color);
  background: var(--card-bg);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  text-decoration: none;
  color: var(--text-primary);
  text-align: center;
}

.btn-action:hover {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
  transform: translateY(-2px);
}

.btn-action.highlight {
  background: linear-gradient(135deg, var(--secondary), #d97706);
  color: white;
  border: none;
}

.btn-action.highlight:hover {
  opacity: 0.9;
  transform: translateY(-2px);
}

.progress-container {
  margin-top: 16px;
}

.progress-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
  font-weight: 600;
}

.progress-bar {
  width: 100%;
  height: 6px;
  background: var(--light-bg);
  border-radius: 3px;
  overflow: hidden;
  border: 1px solid var(--border-color);
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary), var(--secondary));
  border-radius: 3px;
  transition: width 0.6s ease;
}

@media (max-width: 768px) {
  .search-form {
    grid-template-columns: 1fr;
  }
  .result-item {
    grid-template-columns: 1fr;
  }
  .navbar-top {
    flex-direction: column;
    align-items: flex-start;
  }
  .results-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .results-meta {
    flex-direction: column;
  }
}

/* ===== FOOTER ===== */
.footer {
  margin-top: 48px;
  padding: 24px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
  border-top: 1px solid var(--border-color);
}

.footer strong {
  color: var(--text-primary);
}

/* ===== NO RESULTS ===== */
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-secondary);
}

.empty-state-icon {
  font-size: 56px;
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-state h3 {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-primary);
}

.empty-state p {
  font-size: 14px;
  margin: 0;
}

</style>
</head>
<body>

<div class="container-main">
  <!-- HEADER -->
  <div class="navbar-top">
    <div class="navbar-brand-section">
      <div class="logo-badge">📚</div>
      <div class="brand-info">
        <h1>DocVista</h1>
        <p>Intelligent Document Search Engine</p>
      </div>
    </div>
    <div class="navbar-actions">
      <button class="theme-toggle" id="themeToggle" title="Toggle dark mode">🌙</button>
      <a class="btn-sm-header" href="/bm25" title="Learn about BM25 algorithm">ℹ️ BM25 Info</a>
      <a class="btn-sm-header" href="/refresh" title="Reload documents">🔄 Reload</a>
    </div>
  </div>

  <!-- MAIN UNIFIED FORM -->
  <form id="mainForm" method="POST" action="/" enctype="multipart/form-data">
    
    <!-- SEARCH CARD -->
    <div class="search-card">
      <div class="search-title">🔎 Search Documents</div>
      <div class="search-form">
        <input 
          type="text" 
          id="queryInput" 
          name="query" 
          class="form-input" 
          placeholder="Search your documents — try 'deadlock', 'cpu', or any keyword..." 
        />
        <select name="method" class="form-select" title="Choose ranking algorithm">
          <option value="tfidf">TF–IDF</option>
          <option value="bm25">BM25</option>
        </select>
        <button type="submit" class="btn-search">
          <i class="fas fa-search"></i> Search
        </button>
        <div class="upload-row">
          <div class="file-input-wrapper">
            <input type="file" name="file" accept=".pdf,.docx,.txt" id="fileInput" />
            <label for="fileInput" class="file-input-label">
              <i class="fas fa-upload"></i> Choose file
            </label>
          </div>
          <button type="submit" name="upload" value="1" class="btn-upload" title="Upload new document">
            <i class="fas fa-arrow-up"></i>
          </button>
        </div>
      </div>
      <div class="upload-hint">
        <i class="fas fa-info-circle"></i> Supported formats: PDF, DOCX, TXT • Or drop files in <code>/documents</code> folder
      </div>
    </div>

    <!-- FOLDER SELECTION CARD -->
    <div class="search-card" style="margin-top: 20px;">
      <div class="search-title">📁 Select Folder & Search</div>
      <div class="search-form" style="flex-wrap: wrap;">
        <!-- Folder path input field -->
        <input 
          type="text" 
          name="folder_path" 
          class="form-input" 
          id="folderPathDisplay"
          placeholder="Enter folder path (e.g., C:\Users\Documents or /home/user/documents)" 
          value="{{ current_folder }}"
          style="flex: 1; min-width: 300px;"
        />
        
        <label style="display: flex; align-items: center; gap: 8px; margin-top: 10px; flex: 1; min-width: 200px;">
          <input type="checkbox" name="recursive" id="recursiveCheck" />
          <span style="font-size: 14px; color: var(--text-secondary);">📂 Recursive (include subfolders)</span>
        </label>
        
        <button type="submit" name="folder_action" value="select" class="btn-search" style="margin-top: 10px;">
          <i class="fas fa-folder-open"></i> Load Folder
        </button>
      </div>
      
      <!-- Help text with examples -->
      <div style="margin-top: 12px; padding: 12px; border-radius: 4px; background: var(--bg-secondary); border-left: 4px solid #667eea;">
        <div style="font-size: 13px; color: var(--text-secondary); line-height: 1.6;">
          <strong>📌 How to use:</strong>
          <br>1. Enter the full path to your folder above
          <br>2. Examples:
          <div style="margin-left: 20px; font-family: monospace; color: #10b981; margin-top: 4px;">
            <code>Windows: C:\Users\Documents\Research</code>
            <br><code>Mac/Linux: /home/user/documents</code>
          </div>
          <br>3. Check "Recursive" to search subfolders
          <br>4. Click "Load Folder" to load documents
          <br>5. Enter search query above and click Search
        </div>
      </div>
      
      {% if folder_status %}
      <div style="margin-top: 12px; padding: 10px; border-radius: 4px; {% if 'Loaded' in folder_status %}background: rgba(16, 185, 129, 0.1); color: #10b981; border-left: 4px solid #10b981;{% else %}background: rgba(239, 68, 68, 0.1); color: #ef4444; border-left: 4px solid #ef4444;{% endif %} font-size: 13px;">
        {{ folder_status }}
      </div>
      {% endif %}
    </div>

  </form>

  <!-- RESULTS -->
  {% if results %}
  <div class="results-header">
    <div class="results-meta">
      <div class="query-badge">
        <i class="fas fa-quote-left"></i> <strong>{{ query }}</strong>
      </div>
      <div class="doc-count">
        <i class="fas fa-file"></i> {{ n_docs }} documents indexed
      </div>
    </div>
    <form method="POST" action="/export">
      <input type="hidden" name="query" value="{{ query }}">
      <input type="hidden" name="method" value="{{ method }}">
      <button type="submit" class="btn-export-main">
        <i class="fas fa-download"></i> Download Full Report
      </button>
    </form>
  </div>

  {% for r in results %}
  <div class="result-item">
    <div class="result-content">
      <h3><i class="fas fa-file-text"></i> {{ r.name }}</h3>
      <div class="result-meta">
        <div class="meta-item">
          <span class="score-badge">{{ r.score }} • {{ (r.score * 100)|round(0) }}%</span>
        </div>
        <div class="meta-item">
          <i class="fas fa-layer-group"></i> 
          <span>{{ method | upper }}</span>
        </div>
      </div>
      <div class="snippet">{{ r.snippet | safe }}</div>
      <div class="keywords-section">
        <a href="#" class="view-kws-btn" data-idx="{{ r.index }}">
          <i class="fas fa-tags"></i> View Top Keywords
        </a>
        <div id="kws-{{ r.index }}" class="keywords-box" style="display:none;"></div>
      </div>
    </div>
    <div class="result-actions">
      <a class="btn-action" href="/download/{{ r.index }}" title="Download raw document">
        <i class="fas fa-download"></i> Download
      </a>
      {% if r.name.lower().endswith('.pdf') %}
      <a class="btn-action highlight" href="/highlight/{{ r.index }}/{{ query | urlencode }}/{{ method }}" title="Download with highlighted terms">
        <i class="fas fa-highlighter"></i> Highlight PDF
      </a>
      {% endif %}
      <form method="POST" action="/export" style="display:contents;">
        <input type="hidden" name="query" value="{{ query }}">
        <input type="hidden" name="method" value="{{ method }}">
        <input type="hidden" name="single" value="{{ r.index }}">
        <button type="submit" class="btn-action" title="Export this document as PDF report">
          <i class="fas fa-file-pdf"></i> Export Report
        </button>
      </form>
      <div class="progress-container">
        <div class="progress-label">Relevance</div>
        <div class="progress-bar">
          <div class="progress-fill" style="width: {{ (r.score * 100)|round(0) }}%"></div>
        </div>
      </div>
    </div>
  </div>
  {% endfor %}

  {% else %}
  {% if request.method == 'POST' %}
  <div class="empty-state">
    <div class="empty-state-icon">🔍</div>
    <h3>No results found</h3>
    <p>Try different search terms or upload more documents</p>
  </div>
  {% endif %}
  {% endif %}

  <!-- FOOTER -->
  <div class="footer">
    <strong>DocVista</strong> · Professional Information Retrieval Engine
    <br>
    Powered by TF–IDF & BM25 · Export & Highlight PDFs · Built for IR Projects
  </div>
</div>

<!-- SCRIPTS -->
<script>
// Theme Toggle
const themeToggle = document.getElementById('themeToggle');
const htmlElement = document.documentElement;

function initTheme() {
  const stored = localStorage.getItem('docvista-theme');
  const prefer = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const isDark = stored ? stored === 'dark' : prefer;
  applyTheme(isDark);
}

function applyTheme(isDark) {
  if (isDark) {
    htmlElement.setAttribute('data-theme', 'dark');
    themeToggle.textContent = '☀️';
    localStorage.setItem('docvista-theme', 'dark');
  } else {
    htmlElement.removeAttribute('data-theme');
    themeToggle.textContent = '🌙';
    localStorage.setItem('docvista-theme', 'light');
  }
}

themeToggle.addEventListener('click', () => {
  const isDark = htmlElement.getAttribute('data-theme') === 'dark';
  applyTheme(!isDark);
});

initTheme();

// View Keywords
document.addEventListener('click', function(e){
  if (e.target && (e.target.classList.contains('view-kws-btn') || e.target.closest('.view-kws-btn'))) {
    e.preventDefault();
    const link = e.target.closest('.view-kws-btn');
    const idx = link.dataset.idx;
    const box = document.getElementById('kws-' + idx);
    if (!box) return;
    
    if (box.style.display === 'block') { 
      box.style.display = 'none';
      link.innerHTML = '<i class="fas fa-tags"></i> View Top Keywords';
      return; 
    }
    
    box.innerHTML = '<div style="text-align:center;"><i class="fas fa-spinner fa-spin"></i> Loading...</div>';
    fetch('/keywords/' + idx).then(r => r.json()).then(js => {
      if (Array.isArray(js) && js.length > 0) {
        const kws = js.map(k => `<span class="keyword-item">${k}</span>`).join('');
        box.innerHTML = kws;
      } else {
        box.innerHTML = '<div style="color:#ef4444;"><i class="fas fa-exclamation-circle"></i> No keywords found</div>';
      }
      box.style.display = 'block';
      link.innerHTML = '<i class="fas fa-times"></i> Hide Keywords';
    }).catch(_=>{ 
      box.innerHTML = '<div style="color:#ef4444;"><i class="fas fa-exclamation-circle"></i> Error fetching keywords</div>'; 
      box.style.display='block';
      link.innerHTML = '<i class="fas fa-times"></i> Hide Keywords';
    });
  }
});

// File input visual feedback
const fileInput = document.getElementById('fileInput');
fileInput?.addEventListener('change', function() {
  const label = this.nextElementSibling;
  if (this.files && this.files[0]) {
    label.textContent = `✓ ${this.files[0].name}`;
    label.style.borderColor = '#10b981';
    label.style.color = '#10b981';
  }
});

// Folder path input validation and handling
const folderPathDisplay = document.getElementById('folderPathDisplay');
const mainForm = document.getElementById('mainForm');

folderPathDisplay?.addEventListener('focus', function() {
  this.style.borderColor = '#667eea';
});

folderPathDisplay?.addEventListener('blur', function() {
  if (this.value.trim()) {
    this.style.borderColor = 'var(--border-color)';
  }
});
</script>

</body>
</html>
"""

# ----------------------------
# Instantiate engine before routes
# ----------------------------
engine = IREngine()

# ----------------------------
# Routes
# ----------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    results = None
    query = ""
    method = "tfidf"
    folder_status = ""
    if request.method == "POST":
        # folder selection handling
        if request.form.get("folder_action") == "select":
            folder_path = request.form.get("folder_path", "").strip()
            recursive = request.form.get("recursive") == "on"
            
            if folder_path and os.path.isdir(folder_path):
                if engine.load_from_folder(folder_path, recursive=recursive):
                    num_docs = len(engine.doc_names)
                    doc_text = "document" if num_docs == 1 else "documents"
                    folder_status = f"✅ Loaded from: {folder_path} ({num_docs} {doc_text}, {'recursive' if recursive else 'direct'})"
                else:
                    folder_status = f"❌ Failed to load from: {folder_path}"
            else:
                folder_status = f"❌ Invalid folder path: {folder_path}"
        
        # upload handling: only when upload button submitted
        if request.form.get("upload") == "1":
            f = request.files.get("file")
            if f:
                fn = secure_filename(f.filename)
                if fn and fn.lower().endswith(ALLOWED_EXT):
                    path = os.path.join(engine.current_folder, fn)
                    f.save(path)
                    engine.refresh()
        
        # search handling (if query provided)
        query = request.form.get("query", "").strip()
        method = request.form.get("method", "tfidf")
        if query:
            results = engine.search(query, method=method, top_k=20)
    
    return render_template_string(
        BASE_HTML, 
        results=results, 
        n_docs=len(engine.doc_names), 
        query=query, 
        method=method,
        current_folder=engine.current_folder,
        folder_status=folder_status
    )

@app.route("/refresh")
def refresh():
    engine.refresh()
    return redirect(url_for("home"))

@app.route("/download/<int:idx>")
def download_doc(idx):
    if idx < 0 or idx >= len(engine.doc_paths):
        return "Invalid document", 404
    path = engine.doc_paths[idx]
    name = engine.doc_names[idx]
    try:
        if path.lower().endswith(".pdf"):
            return send_file(path, as_attachment=True, download_name=name, mimetype="application/pdf")
        else:
            txt = engine.docs_raw[idx]
            buf = io.BytesIO()
            buf.write(txt.encode("utf-8", errors="ignore"))
            buf.seek(0)
            return send_file(buf, as_attachment=True, download_name=f"{name}.txt", mimetype="text/plain")
    except Exception as e:
        return f"Error sending file: {e}", 500

@app.route("/keywords/<int:idx>")
def keywords(idx):
    if idx < 0 or idx >= len(engine.doc_names):
        return jsonify({"error": "invalid index"}), 404
    try:
        kws = engine.top_keywords(idx, top_n=12)
        return jsonify(kws)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/highlight/<int:idx>/<query>/<method>")
def highlight_route(idx, query, method):
    if idx < 0 or idx >= len(engine.doc_paths):
        return "Invalid document", 404
    path = engine.doc_paths[idx]
    if not path.lower().endswith(".pdf"):
        return "<h3>Highlighting only supported for PDF files.</h3><a href='/'>Back</a>"
    q = unquote_plus(query)
    q_tokens = normalize_for_index(preprocess(q)).split()
    try:
        out_buf = highlight_pdf_bytes(path, q_tokens)
    except Exception as e:
        return f"<h3>Highlight error</h3><pre>{e}</pre><a href='/'>Back</a>"
    name = f"highlighted_{engine.doc_names[idx]}"
    return send_file(out_buf, as_attachment=True, download_name=name, mimetype="application/pdf")

@app.route("/export", methods=["POST"])
def export_report_route():
    q = request.form.get("query", "").strip()
    method = request.form.get("method", "tfidf")
    single = request.form.get("single", None)
    if not q:
        return redirect(url_for("home"))
    if single is not None and single != "":
        try:
            idx = int(single)
        except Exception:
            return "<h3>Invalid single index</h3><a href='/'>Back</a>"
        results = engine.search(q, method=method, top_k=50)
        results = [r for r in results if r["index"] == idx]
    else:
        results = engine.search(q, method=method, top_k=50)
    pdf_buf = create_search_report_pdf(q, method, results)
    fname = f"docvista_report_{int(time.time())}.pdf"
    return send_file(pdf_buf, as_attachment=True, download_name=fname, mimetype="application/pdf")

@app.route("/bm25")
def bm25_info():
    html = """
    <!doctype html>
    <html lang="en">
    <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width,initial-scale=1"/>
    <title>BM25 Algorithm — DocVista</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
    * {margin:0;padding:0;box-sizing:border-box;}
    :root {
      --primary: #3956ff;
      --primary-dark: #1e3a8a;
      --secondary: #f59e0b;
      --success: #10b981;
      --danger: #ef4444;
      --light-bg: #f8fafc;
      --card-bg: #ffffff;
      --text-primary: #0f172a;
      --text-secondary: #64748b;
      --border-color: #e2e8f0;
      --shadow-md: 0 4px 16px rgba(15, 23, 42, 0.12);
      --shadow-lg: 0 8px 24px rgba(15, 23, 42, 0.15);
    }
    [data-theme="dark"] {
      --light-bg: #0f172a;
      --card-bg: #1e293b;
      --text-primary: #f1f5f9;
      --text-secondary: #cbd5e1;
      --border-color: #334155;
    }
    html, body {
      background: var(--light-bg);
      color: var(--text-primary);
      transition: background-color 0.3s ease, color 0.3s ease;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
      line-height: 1.6;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    body { padding: 24px 16px; }
    .container {
      max-width: 900px;
      margin: 0 auto;
      flex: 1;
      display: flex;
      flex-direction: column;
    }
    /* HEADER */
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 32px;
      gap: 16px;
      flex-wrap: wrap;
    }
    .back-btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 16px;
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      color: var(--text-primary);
      text-decoration: none;
      font-weight: 600;
      font-size: 14px;
      transition: all 0.3s ease;
    }
    .back-btn:hover {
      background: var(--primary);
      color: white;
      border-color: var(--primary);
      gap: 12px;
    }
    .theme-toggle {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 8px 12px;
      cursor: pointer;
      font-size: 16px;
      transition: all 0.3s ease;
    }
    .theme-toggle:hover {
      background: var(--light-bg);
      border-color: var(--primary);
    }
    .title {
      font-size: 32px;
      font-weight: 700;
      margin-bottom: 8px;
      background: linear-gradient(135deg, var(--primary), var(--secondary));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    .subtitle {
      font-size: 14px;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 1px;
    }
    /* MAIN CONTENT */
    .content {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 14px;
      padding: 28px;
      box-shadow: var(--shadow-md);
      transition: all 0.3s ease;
    }
    .card:hover {
      box-shadow: var(--shadow-lg);
      transform: translateY(-2px);
    }
    .card-title {
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--text-primary);
    }
    .card-title i {
      color: var(--primary);
    }
    .card-text {
      font-size: 14px;
      line-height: 1.7;
      color: var(--text-secondary);
      margin-bottom: 16px;
    }
    .formula-box {
      background: linear-gradient(135deg, rgba(57, 86, 255, 0.05), rgba(245, 158, 11, 0.05));
      border: 1px solid rgba(57, 86, 255, 0.2);
      border-radius: 10px;
      padding: 20px;
      margin: 16px 0;
      font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
      font-size: 13px;
      overflow-x: auto;
      line-height: 1.8;
      color: var(--primary);
    }
    .param-list {
      list-style: none;
      margin: 12px 0;
    }
    .param-list li {
      padding: 10px 0;
      border-bottom: 1px solid var(--border-color);
      display: flex;
      gap: 12px;
      align-items: flex-start;
    }
    .param-list li:last-child {
      border-bottom: none;
    }
    .param-label {
      font-weight: 600;
      color: var(--primary);
      min-width: 60px;
      font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
      font-size: 13px;
    }
    .param-desc {
      color: var(--text-secondary);
      font-size: 13px;
    }
    .comparison {
      background: var(--light-bg);
      border-radius: 10px;
      overflow: hidden;
      margin: 16px 0;
    }
    .comparison-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      border-bottom: 1px solid var(--border-color);
    }
    .comparison-row:last-child {
      border-bottom: none;
    }
    .comparison-cell {
      padding: 14px;
      font-size: 13px;
    }
    .comparison-cell:first-child {
      background: rgba(57, 86, 255, 0.05);
      font-weight: 600;
      color: var(--primary);
      border-right: 1px solid var(--border-color);
    }
    .feature-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin: 12px 0;
    }
    .feature-item {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 10px;
      background: var(--light-bg);
      border-radius: 8px;
      font-size: 13px;
      color: var(--text-secondary);
    }
    .feature-item i {
      color: var(--success);
      margin-top: 2px;
      flex-shrink: 0;
    }
    .btn-primary {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 12px 24px;
      background: linear-gradient(135deg, var(--primary), var(--primary-dark));
      color: white;
      border: none;
      border-radius: 8px;
      font-weight: 600;
      font-size: 14px;
      cursor: pointer;
      text-decoration: none;
      transition: all 0.3s ease;
      margin-top: 16px;
    }
    .btn-primary:hover {
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(57, 86, 255, 0.3);
    }
    /* FOOTER */
    .footer {
      margin-top: 48px;
      padding-top: 24px;
      border-top: 1px solid var(--border-color);
      text-align: center;
      color: var(--text-secondary);
      font-size: 13px;
    }
    .footer strong {
      color: var(--text-primary);
    }
    @media (max-width: 768px) {
      .content {
        grid-template-columns: 1fr;
      }
      .comparison-row {
        grid-template-columns: 1fr;
      }
      .comparison-cell:first-child {
        border-right: none;
        border-bottom: 1px solid var(--border-color);
      }
      .title {
        font-size: 24px;
      }
    }
    </style>
    </head>
    <body>
    <div class="container">
      <!-- HEADER -->
      <div class="header">
        <div>
          <h1 class="title">BM25 Algorithm</h1>
          <p class="subtitle">Probabilistic Ranking Function for Information Retrieval</p>
        </div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <button class="theme-toggle" id="themeToggle" title="Toggle dark mode">🌙</button>
          <a href="/" class="back-btn"><i class="fas fa-arrow-left"></i> Back to Search</a>
        </div>
      </div>

      <!-- MAIN CONTENT -->
      <div class="content">
        <!-- ABOUT BM25 -->
        <div class="card">
          <h2 class="card-title">
            <i class="fas fa-book"></i> What is BM25?
          </h2>
          <p class="card-text">
            BM25 (Best Match 25) is a probabilistic ranking function widely used in modern search engines and information retrieval systems. It combines term frequency, inverse document frequency, and document length normalization to produce highly relevant search results.
          </p>
          <p class="card-text">
            BM25 is considered superior to traditional TF-IDF because it accounts for document length saturation, preventing long documents from dominating results.
          </p>
          <div class="feature-list">
            <div class="feature-item">
              <i class="fas fa-check-circle"></i>
              <span><strong>Probabilistic:</strong> Based on probability theory and information retrieval models</span>
            </div>
            <div class="feature-item">
              <i class="fas fa-check-circle"></i>
              <span><strong>Length-aware:</strong> Normalizes scores based on document length</span>
            </div>
            <div class="feature-item">
              <i class="fas fa-check-circle"></i>
              <span><strong>Tunable:</strong> Configurable parameters for different use cases</span>
            </div>
          </div>
        </div>

        <!-- THE FORMULA -->
        <div class="card">
          <h2 class="card-title">
            <i class="fas fa-calculator"></i> The Formula
          </h2>
          <div class="formula-box">
score(D,Q) = Σ IDF(q)<br>
· (f(q,D) · (k₁ + 1))<br>
────────────────────<br>
f(q,D) + k₁(1 - b<br>
+ b · |D| / avgdl)
          </div>
          <p class="card-text" style="margin-top: 16px; font-size: 12px;">
            Where each term in the query contributes to the total relevance score based on its frequency in the document and across the corpus.
          </p>
        </div>

        <!-- PARAMETERS -->
        <div class="card">
          <h2 class="card-title">
            <i class="fas fa-sliders-h"></i> Parameters
          </h2>
          <ul class="param-list">
            <li>
              <span class="param-label">IDF(q)</span>
              <span class="param-desc">Inverse Document Frequency of query term — measures rarity across corpus</span>
            </li>
            <li>
              <span class="param-label">f(q,D)</span>
              <span class="param-desc">Term frequency of query term in document D</span>
            </li>
            <li>
              <span class="param-label">|D|</span>
              <span class="param-desc">Length of document D (in words/tokens)</span>
            </li>
            <li>
              <span class="param-label">avgdl</span>
              <span class="param-desc">Average document length in the entire corpus</span>
            </li>
            <li>
              <span class="param-label">k₁</span>
              <span class="param-desc">Controls term frequency saturation (default: 1.5)</span>
            </li>
            <li>
              <span class="param-label">b</span>
              <span class="param-desc">Controls length normalization (0.0 = none, 1.0 = full)</span>
            </li>
          </ul>
        </div>

        <!-- COMPARISON -->
        <div class="card">
          <h2 class="card-title">
            <i class="fas fa-scale-balanced"></i> BM25 vs TF-IDF
          </h2>
          <div class="comparison">
            <div class="comparison-row">
              <div class="comparison-cell">Aspect</div>
              <div class="comparison-cell">BM25 / TF-IDF</div>
            </div>
            <div class="comparison-row">
              <div class="comparison-cell">Term Frequency</div>
              <div class="comparison-cell">Saturates (diminishing returns)</div>
            </div>
            <div class="comparison-row">
              <div class="comparison-cell">Length Normalization</div>
              <div class="comparison-cell">Advanced tuning / Simple</div>
            </div>
            <div class="comparison-row">
              <div class="comparison-cell">Document Length Bias</div>
              <div class="comparison-cell">Minimal / Prone to long docs</div>
            </div>
            <div class="comparison-row">
              <div class="comparison-cell">Ranking Quality</div>
              <div class="comparison-cell">Superior / Good baseline</div>
            </div>
          </div>
        </div>

        <!-- USE CASES -->
        <div class="card">
          <h2 class="card-title">
            <i class="fas fa-lightbulb"></i> Use Cases
          </h2>
          <div class="feature-list">
            <div class="feature-item">
              <i class="fas fa-search"></i>
              <span>Web search engines (Google, Bing use variants)</span>
            </div>
            <div class="feature-item">
              <i class="fas fa-search"></i>
              <span>Enterprise full-text search (Elasticsearch, Solr)</span>
            </div>
            <div class="feature-item">
              <i class="fas fa-search"></i>
              <span>Document retrieval systems</span>
            </div>
            <div class="feature-item">
              <i class="fas fa-search"></i>
              <span>Question answering systems</span>
            </div>
            <div class="feature-item">
              <i class="fas fa-search"></i>
              <span>Academic paper ranking</span>
            </div>
          </div>
        </div>

        <!-- TUNING GUIDE -->
        <div class="card">
          <h2 class="card-title">
            <i class="fas fa-wrench"></i> Parameter Tuning
          </h2>
          <p class="card-text">
            <strong>k₁ (1.5 default):</strong> Higher values increase term frequency impact. Range: 0.5-3.0
          </p>
          <p class="card-text">
            <strong>b (0.75 default):</strong> Controls length normalization strength. 0 = off, 1 = full
          </p>
          <p class="card-text">
            For short texts like tweets: Lower k₁ (0.9) and higher b (0.8)
          </p>
          <p class="card-text">
            For long documents: Higher k₁ (2.0) and lower b (0.3)
          </p>
        </div>
      </div>

      <!-- FOOTER -->
      <div class="footer">
        <strong>DocVista</strong> · BM25 Education Center
        <br>
        Learn more about advanced information retrieval ranking algorithms
      </div>
    </div>

    <script>
    // Theme Toggle
    const themeToggle = document.getElementById('themeToggle');
    const htmlElement = document.documentElement;

    function initTheme() {
      const stored = localStorage.getItem('docvista-theme');
      const prefer = window.matchMedia('(prefers-color-scheme: dark)').matches;
      const isDark = stored ? stored === 'dark' : prefer;
      applyTheme(isDark);
    }

    function applyTheme(isDark) {
      if (isDark) {
        htmlElement.setAttribute('data-theme', 'dark');
        themeToggle.textContent = '☀️';
        localStorage.setItem('docvista-theme', 'dark');
      } else {
        htmlElement.removeAttribute('data-theme');
        themeToggle.textContent = '🌙';
        localStorage.setItem('docvista-theme', 'light');
      }
    }

    themeToggle.addEventListener('click', () => {
      const isDark = htmlElement.getAttribute('data-theme') === 'dark';
      applyTheme(!isDark);
    });

    initTheme();
    </script>
    </body>
    </html>
    """
    return html

# ----------------------------
# Run
# ----------------------------
if __name__ == "__main__":
    print("Loading documents from:", os.path.abspath(DOCS_FOLDER))
    print("Open http://127.0.0.1:5000")
    # ensure engine exists and built
    engine = IREngine()
    app.run(debug=True, port=5000)
