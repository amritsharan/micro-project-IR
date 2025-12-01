# ============================================
# engine.py - DocVista IR Engine
# Core Modules + Extract + Index + Search
# ============================================

import os
import io
import re
import fitz   # PyMuPDF for PDF highlighting
import string
import json
from math import log
from pathlib import Path
from fpdf import FPDF

from flask import (
    Flask, request, render_template_string,
    send_file, redirect, url_for, jsonify
)
from werkzeug.utils import secure_filename

import docx
import PyPDF2
import numpy as np
import unicodedata
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ===============================
# Configurations
# ===============================
DOCS_FOLDER = "documents"
ALLOWED_EXT = (".txt", ".pdf", ".docx")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB

# ===============================
# Text Extraction Utilities
# ===============================

def extract_text_from_pdf(path):
    """Extract text from PDF using PyPDF2."""
    out = ""
    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for p in reader.pages:
                txt = p.extract_text()
                if txt:
                    out += txt + " "
    except Exception:
        pass
    return out


def extract_text_from_docx(path):
    try:
        doc = docx.Document(path)
        return " ".join([p.text for p in doc.paragraphs])
    except:
        return ""


def extract_text_from_txt(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except:
        return ""

def preprocess(text):
    """Normalize whitespace without removing data."""
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_index(text):
    """Lowercase + remove punctuation for token-level ranking."""
    text = text.lower()
    return text.translate(str.maketrans("", "", string.punctuation))


# ===============================
# Load documents
# ===============================

def load_documents(folder=DOCS_FOLDER):
    docs_raw, names, paths = [], [], []
    os.makedirs(folder, exist_ok=True)

    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(ALLOWED_EXT):
            continue

        fp = os.path.join(folder, fname)

        if fname.endswith(".pdf"):
            raw = extract_text_from_pdf(fp)
        elif fname.endswith(".docx"):
            raw = extract_text_from_docx(fp)
        else:
            raw = extract_text_from_txt(fp)

        raw = preprocess(raw)

        if len(raw) > 10:
            docs_raw.append(raw)
            names.append(fname)
            paths.append(fp)

    return docs_raw, names, paths


# ===============================
# BM25 Implementation
# ===============================

class BM25Simple:
    def __init__(self, docs_tokens):
        self.docs_tokens = docs_tokens
        self.N = len(docs_tokens)
        self.avgdl = sum(len(d) for d in docs_tokens) / self.N if self.N else 0

        self.doc_freqs = []
        self.df = {}

        for doc in docs_tokens:
            f = {}
            for w in doc:
                f[w] = f.get(w, 0) + 1
            self.doc_freqs.append(f)

            for w in f:
                self.df[w] = self.df.get(w, 0) + 1

        # IDF
        self.idf = {
            w: log(1 + (self.N - freq + 0.5) / (freq + 0.5))
            for w, freq in self.df.items()
        }

        self.k1 = 1.5
        self.b = 0.75

    def score(self, q_tokens):
        scores = [0.0] * self.N
        for q in q_tokens:
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


# ===============================
# Search Engine
# ===============================

class IREngine:
    def __init__(self):
        self.docs_raw, self.doc_names, self.doc_paths = load_documents(DOCS_FOLDER)
        self._build()

    def _build(self):
        self.vectorizer = TfidfVectorizer(stop_words="english")
        if self.docs_raw:
            self.doc_vectors = self.vectorizer.fit_transform(self.docs_raw)
        else:
            self.doc_vectors = None

        self.docs_tokens = [normalize_for_index(d).split() for d in self.docs_raw]
        self.bm25 = BM25Simple(self.docs_tokens) if self.docs_tokens else None

    def refresh(self):
        self.docs_raw, self.doc_names, self.doc_paths = load_documents(DOCS_FOLDER)
        self._build()

    def search(self, query, method="tfidf", top_k=10):
        query_plain = preprocess(query)
        query_norm = normalize_for_index(query_plain)
        q_tokens = [w for w in query_norm.split() if w]

        results = []

        if method.lower() == "bm25" and self.bm25:
            scores = self.bm25.score(q_tokens)
            ranked = np.argsort(scores)[::-1]
            for i in ranked[:top_k]:
                results.append((i, float(scores[i])))
        else:
            if self.doc_vectors is None:
                return []
            q_vec = self.vectorizer.transform([query_plain])
            sims = cosine_similarity(q_vec, self.doc_vectors)[0]
            ranked = np.argsort(sims)[::-1]
            for i in ranked[:top_k]:
                results.append((i, float(sims[i])))

        enriched = []
        for idx, score in results:
            snip = extract_snippet(self.docs_raw[idx], q_tokens)
            enriched.append({
                "index": idx,
                "name": self.doc_names[idx],
                "path": self.doc_paths[idx],
                "score": round(score, 4),
                "snippet": snip
            })
        return enriched


# ===============================
# Snippet Extractor + Highlighter
# ===============================

def extract_snippet(text, tokens, window=200):
    low = text.lower()
    pos = -1
    for t in tokens:
        p = low.find(t)
        if p != -1:
            pos = p
            break

    if pos == -1:
        sn = text[:window] + ("..." if len(text) > window else "")
    else:
        start = max(0, pos - window // 2)
        end = min(len(text), start + window)
        sn = text[start:end]
        if start > 0:
            sn = "..." + sn
        if end < len(text):
            sn += "..."

    # highlight
    for t in set(tokens):
        if t:
            sn = re.sub(fr"(?i)({re.escape(t)})", r"<mark>\1</mark>", sn)
    return sn


# ============================================
# HTML Template + UI
# ============================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>DocVista: Smart Multi-Format IR Engine</title>

<style>
    body {
        font-family: Arial;
        margin: 0;
        padding: 0;
        background: var(--bg);
        color: var(--text);
        transition: background 0.4s, color 0.4s;
    }

    :root {
        --bg: #ffffff;
        --text: #000000;
        --card: #f5f5f5;
        --accent: #007bff;
        --progress: #4caf50;
        --shadow: rgba(0,0,0,0.15);
    }

    body[data-theme="dark"] {
        --bg: #121212;
        --text: #ffffff;
        --card: #1e1e1e;
        --accent: #4da3ff;
        --progress: #5dd37e;
        --shadow: rgba(255,255,255,0.08);
    }

    .container {
        max-width: 900px;
        margin: 40px auto;
        padding: 20px;
    }

    h1 {
        text-align: center;
        margin-bottom: 20px;
    }

    .box {
        background: var(--card);
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 15px var(--shadow);
        margin-bottom: 20px;
        animation: fadeSlide 0.5s ease;
    }

    @keyframes fadeSlide {
        from { opacity: 0; transform: translateY(15px); }
        to   { opacity: 1; transform: translateY(0); }
    }

    input, select, button {
        padding: 10px;
        border-radius: 8px;
        border: none;
        margin-right: 10px;
        font-size: 15px;
    }

    button {
        cursor: pointer;
        background: var(--accent);
        color: white;
    }

    .result {
        opacity: 0;
        transform: translateY(10px);
        transition: opacity 0.4s, transform 0.4s;
    }

    .result.show {
        opacity: 1;
        transform: translateY(0);
    }

    .snippet {
        background: var(--card);
        padding: 10px;
        border-radius: 6px;
        line-height: 1.4;
        margin-top: 8px;
    }

    .progress-bar {
        width: 100%;
        background: #ccc;
        border-radius: 10px;
        margin-top: 8px;
        height: 12px;
    }

    .progress {
        height: 100%;
        background: var(--progress);
        border-radius: 10px;
        width: 0%;
        transition: width 1s;
    }

    .modal-bg {
        position: fixed;
        top: 0; left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.5);
        display: none;
        align-items: center;
        justify-content: center;
    }

    .modal {
        background: var(--card);
        color: var(--text);
        padding: 20px;
        border-radius: 10px;
        min-width: 300px;
        max-width: 400px;
        box-shadow: 0 4px 15px var(--shadow);
    }

    .close-btn {
        float: right;
        cursor: pointer;
        color: var(--accent);
        font-weight: bold;
    }

</style>
</head>

<body data-theme="light">
<div class="container">
    <h1>DocVista: Smart Multi-Format Search Engine</h1>

    <!-- SEARCH BOX -->
    <div class="box">
        <form method="POST" action="/" id="searchForm">
            <input id="queryInput" name="query" placeholder="Enter search query..." size="40" />

            <select name="method">
                <option value="tfidf">TF-IDF</option>
                <option value="bm25">BM25</option>
            </select>

            <button type="submit">Search</button>
            <button type="button" id="clearBtn">Clear</button>
            <button type="button" id="themeToggle">🌙</button>
        </form>

        <h3 style="margin-top:20px;">Recent Searches</h3>
        <ul id="historyList"></ul>
    </div>

    <!-- RESULTS -->
    {% if results %}
        <div class="box">
            <h2>Search Results</h2>
            {% for r in results %}
                <div class="result box">
                    <h3>{{r.name}}</h3>
                    <div>Score: {{r.score}}</div>

                    <!-- Progress Bar -->
                    <div class="progress-bar">
                        <div class="progress" style="width: {{r.score * 100}}%;"></div>
                    </div>

                    <div class="snippet">{{r.snippet|safe}}</div>

                    <br>

                    <a href="/download/{{r.index}}">📄 Download</a> &nbsp;&nbsp;
                    <a href="/highlight/{{r.index}}/{{query}}/{{method}}">✨ Highlight PDF</a> &nbsp;&nbsp;
                    <a href="#" onclick="openKeywords({{r.index}})">🔍 TF-IDF Keywords</a>
                </div>
            {% endfor %}
        </div>
    {% endif %}

    <div style="margin-top:30px;">
        <a href="/bm25">📘 Learn about BM25</a>
    </div>
</div>

<!-- Keyword Modal -->
<div class="modal-bg" id="modalBg">
    <div class="modal">
        <span class="close-btn" onclick="closeModal()">X</span>
        <h3>Top TF-IDF Keywords</h3>
        <ul id="keywordList"></ul>
    </div>
</div>

<script>
// ==========================
// THEME TOGGLE
// ==========================
const btn = document.getElementById("themeToggle");
const saved = localStorage.getItem("theme") || "light";
document.body.setAttribute("data-theme", saved);
btn.textContent = saved === "dark" ? "☀️" : "🌙";

function switchTheme(){
    const cur = document.body.getAttribute("data-theme");
    const nxt = cur === "dark" ? "light" : "dark";
    document.body.setAttribute("data-theme", nxt);
    btn.textContent = nxt === "dark" ? "☀️" : "🌙";
    localStorage.setItem("theme", nxt);
}
btn.onclick = switchTheme;


// ==========================
// CLEAR SEARCH BOX
// ==========================
document.getElementById("clearBtn").onclick = ()=>{
    document.getElementById("queryInput").value = "";
};


// ==========================
// ANIMATE RESULTS
// ==========================
window.addEventListener("DOMContentLoaded", ()=>{
    document.querySelectorAll(".result").forEach((e,i)=>{
        setTimeout(()=> e.classList.add("show"), i * 120);
    });
});


// ==========================
// SEARCH HISTORY
// ==========================
const historyList = document.getElementById("historyList");
function loadHistory(){
    let h = JSON.parse(localStorage.getItem("search_history") || "[]");
    historyList.innerHTML = "";
    h.slice(-10).reverse().forEach(q=>{
        historyList.innerHTML += `<li>${q}</li>`;
    });
}
loadHistory();

document.getElementById("searchForm").onsubmit = ()=>{
    let q = document.getElementById("queryInput").value.trim();
    if(!q) return;
    let h = JSON.parse(localStorage.getItem("search_history") || "[]");
    h.push(q);
    localStorage.setItem("search_history", JSON.stringify(h));
};


// ==========================
// TF-IDF KEYWORD MODAL
// ==========================
function openKeywords(idx){
    fetch(`/keywords/${idx}`)
    .then(r=>r.json())
    .then(data=>{
        let box = document.getElementById("keywordList");
        box.innerHTML = "";
        data.forEach(k=>{
            box.innerHTML += `<li>${k}</li>`;
        });
        document.getElementById("modalBg").style.display="flex";
    });
}
function closeModal(){
    document.getElementById("modalBg").style.display="none";
}
</script>

</body>
</html>
"""

# ============================================
# Flask App Routes + Search Logic
# ============================================

@app.route("/", methods=["GET", "POST"])
def home():
    results = None
    query = ""
    method = "tfidf"

    if request.method == "POST":
        query = request.form.get("query", "").strip()
        method = request.form.get("method", "tfidf")

        if query:
            results = engine.search(query, method=method, top_k=20)

    return render_template_string(HTML_TEMPLATE, results=results, query=query, method=method)


@app.route("/download/<int:doc_id>")
def download_doc(doc_id):
    if doc_id < 0 or doc_id >= len(engine.doc_names):
        return "Invalid document", 404
    
    name = engine.doc_names[doc_id]
    text = engine.docs_raw[doc_id]

    buf = io.BytesIO()
    buf.write(text.encode("utf-8", errors="ignore"))
    buf.seek(0)

    return send_file(
        buf,
        download_name=f"{name}.txt",
        as_attachment=True,
        mimetype="text/plain"
    )


@app.route("/keywords/<int:doc_id>")
def keywords(doc_id):
    """
    Return top TF-IDF keywords for the selected document.
    """
    if doc_id < 0 or doc_id >= len(engine.doc_names):
        return jsonify({"error": "Invalid document"}), 404
    
    try:
        top_terms = engine.top_keywords(doc_id, top_n=12)
        return jsonify(top_terms)
    except Exception as e:
        return jsonify({"error": str(e)})


# ============================================
# PDF Export + Keyword extraction
# ============================================

def _safe_get_feature_names(vectorizer):
    try:
        return vectorizer.get_feature_names_out()
    except Exception:
        return vectorizer.get_feature_names()

def top_keywords_for_doc(vectorizer, doc_vector, top_n=10):
    """Return top (term, score) pairs for a single TF-IDF vector (sparse)."""
    features = _safe_get_feature_names(vectorizer)
    if hasattr(doc_vector, "toarray"):
        arr = np.asarray(doc_vector.todense()).ravel()
    else:
        arr = np.asarray(doc_vector).ravel()

    if arr.sum() == 0:
        return []
    indices = np.argsort(arr)[::-1][:top_n]
    return [(features[i], float(arr[i])) for i in indices if arr[i] > 0]


def ire_top_keywords(self, doc_id, top_n=10):
    if self.doc_vectors is None:
        return []
    if doc_id < 0 or doc_id >= len(self.doc_vectors):
        return []
    vec = self.doc_vectors[doc_id]
    kws = top_keywords_for_doc(self.vectorizer, vec, top_n=top_n)
    return [f"{t} ({score:.4f})" for t, score in kws]

IREngine.top_keywords = ire_top_keywords


# ============================================
# PDF text utilities
# ============================================

def normalize_text_for_pdf(text):
    """
    Normalize unicode characters and remove controls that FPDF cannot handle.
    """
    if text is None:
        return ""
    replacements = {
        '\u2013': '-', '\u2014': '-', '\u2015': '-',
        '\u2212': '-', '\u2022': '*', '\u00A0': ' '
    }
    for a, b in replacements.items():
        text = text.replace(a, b)

    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    text = str(text)
    return text

def safe_wrap(text, max_len=60):
    """Insert breaks into very long tokens so FPDF can wrap them."""
    parts = []
    for word in text.split():
        if len(word) > max_len:
            for i in range(0, len(word), max_len):
                parts.append(word[i:i+max_len])
        else:
            parts.append(word)
    return " ".join(parts)

def prepare_pdf_text(text):
    t = normalize_text_for_pdf(text)
    t = safe_wrap(t, max_len=60)
    return t

def _chunks_of(text, max_chars=900):
    """Yield chunks with <= max_chars, try to break at whitespace."""
    if not text:
        return
    start = 0
    L = len(text)
    while start < L:
        end = min(L, start + max_chars)
        if end < L:
            seg = text[start:end]
            last_space = seg.rfind(" ")
            if last_space > int(max_chars * 0.5):
                end = start + last_space
        yield text[start:end].strip()
        start = end


def create_pdf_bytes(query, method, results):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    font_candidates = [
        "fonts/DejaVuSans.ttf", "fonts/ttf/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf"
    ]
    font_path = None
    for c in font_candidates:
        if os.path.exists(c):
            font_path = c
            break

    base_font = "Arial"
    if font_path:
        try:
            pdf.add_font("DejaVu", "", font_path, uni=True)
            base_font = "DejaVu"
        except Exception:
            base_font = "Arial"

    CELL_WIDTH = 180

    pdf.set_font(base_font, size=14)
    title = prepare_pdf_text(f"DocVista — Search Report (Query: {query})")
    for chunk in _chunks_of(title, max_chars=200):
        pdf.multi_cell(CELL_WIDTH, 8, chunk)

    pdf.ln(3)
    pdf.set_font(base_font, size=11)
    header = prepare_pdf_text(f"Ranking: {method.upper()} — Documents: {len(engine.doc_names)}")
    for chunk in _chunks_of(header, max_chars=200):
        pdf.multi_cell(CELL_WIDTH, 6, chunk)

    pdf.ln(6)

    for r in results:
        pdf.set_font(base_font, size=12)
        line = prepare_pdf_text(f"{r['name']}  (Score: {r['score']})")
        for chunk in _chunks_of(line, max_chars=160):
            pdf.multi_cell(CELL_WIDTH, 6, chunk)

        pdf.set_font(base_font, size=10)
        snippet = re.sub(r"<[^>]*>", "", r.get("snippet", ""))
        snippet = prepare_pdf_text(snippet)

        for chunk in _chunks_of(snippet, max_chars=600):
            pdf.multi_cell(CELL_WIDTH, 5, chunk)

        pdf.ln(4)

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf

@app.route("/export", methods=["POST"])
def export_report():
    q = request.form.get("query", "").strip()
    method = request.form.get("method", "tfidf")
    single = request.form.get("single", None)

    if not q:
        return redirect(url_for("home"))

    if single is not None:
        idx = int(single)
        results = engine.search(q, method=method, top_k=50)
        results = [r for r in results if r["index"] == idx]
    else:
        results = engine.search(q, method=method, top_k=50)

    buf = create_pdf_bytes(q, method, results)
    return send_file(buf, download_name="docvista_search_report.pdf", as_attachment=True, mimetype="application/pdf")


# ============================================
# Highlighted PDF View
# ============================================

def highlight_pdf(original_path, query_terms):
    """
    Returns a BytesIO object containing the highlighted PDF.
    """
    doc = fitz.open(original_path)
    query_terms = [q.lower() for q in query_terms if q]

    for page in doc:
        for term in query_terms:
            if term.strip() == "":
                continue
            rects = page.search_for(term)
            for r in rects:
                page.add_highlight_annot(r)

    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True)
    out.seek(0)
    doc.close()
    return out


@app.route("/highlight/<int:idx>/<query>/<method>")
def highlight_view(idx, query, method):
    if idx < 0 or idx >= len(engine.doc_paths):
        return "Invalid", 404
    
    path = engine.doc_paths[idx]
    query_norm = normalize_for_index(query).split()
    buf = highlight_pdf(path, query_norm)

    return send_file(
        buf,
        download_name=f"highlight_{engine.doc_names[idx]}.pdf",
        as_attachment=False,
        mimetype="application/pdf"
    )


# ============================================
# Info Pages
# ============================================

@app.route("/bm25")
def bm25_info():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="UTF-8">
    <title>BM25 Explanation</title>
    <style>
        body { font-family: Arial; margin: 40px; background: #f5f5f5; }
        .box { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        pre { background: #f0f0f0; padding: 10px; border-radius: 5px; overflow-x: auto; }
    </style>
    </head>
    <body>
    <div class="box">
        <h2>BM25 Ranking Model — Explanation</h2>
        <p>BM25 is a probabilistic retrieval function used by modern search engines.</p>
        <h4>Formula:</h4>
        <pre>score(D, Q) = Σ over terms t in Q:
     idf(t) * (f(t, D) * (k1 + 1)) /
                ( f(t, D) + k1 * (1 - b + b * |D| / avgdl) )</pre>

        <b>Where:</b><br>
        • f(t, D): term-frequency in document D<br>
        • |D|: length of document<br>
        • avgdl: average document length<br>
        • k1 = 1.5 (term frequency scaling)<br>
        • b = 0.75 (length normalization)<br>

        <p><b>BM25 usually ranks better than TF–IDF because it handles:</b></p>
        <ul>
            <li>Document length bias</li>
            <li>Diminishing returns on repeated terms</li>
            <li>Non-linear scaling</li>
        </ul>
        <br>
        <a href="/" style="font-size:18px;">⬅ Back</a>
    </div>
    </body>
    </html>
    """
    return html


# ============================================
# Engine Initialization
# ============================================

engine = IREngine()


if __name__ == "__main__":
    app.run(debug=True)
