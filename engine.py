# engine.py — DocVista final single-file app
# Features:
# - Multi-format ingestion: .pdf, .docx, .txt
# - TF-IDF (Scikit-learn) and BM25 ranking
# - Snippets with <mark> highlights
# - TF-IDF top keywords modal
# - PDF highlighting (PyMuPDF) -> downloads highlighted PDF
# - Export search results -> PDF report with dashboard + keywords + percentages
# - Upload UI (Option B), search history (localStorage), dark/light theme
# - Robust handling for encoding/long tokens/FPDF issues

import os
import io
import re
import string
import time
from math import log
from pathlib import Path
from urllib.parse import quote_plus, unquote_plus
import unicodedata

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
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB

# ----------------------------
# Utilities: extract & preprocess
# ----------------------------
def extract_text_from_pdf(path):
    out = ""
    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for p in reader.pages:
                txt = p.extract_text()
                if txt:
                    out += txt + " "
    except Exception:
        # fallback: try PyMuPDF extraction
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

# ----------------------------
# Load documents
# ----------------------------
def load_documents(folder=DOCS_FOLDER):
    docs_raw, names, paths = [], [], []
    os.makedirs(folder, exist_ok=True)
    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(ALLOWED_EXT):
            continue
        fp = os.path.join(folder, fname)
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
        self._build()

    def _build(self):
        self.vectorizer = TfidfVectorizer(stop_words="english")
        if self.docs_raw:
            try:
                self.doc_vectors = self.vectorizer.fit_transform(self.docs_raw)
            except Exception:
                self.doc_vectors = None
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
        q_tokens = [t for t in query_norm.split() if t]
        results = []
        if method.lower() == "bm25" and self.bm25:
            scores = self.bm25.score(q_tokens)
            ranked = np.argsort(scores)[::-1]
            for idx in ranked[:top_k]:
                results.append((idx, float(scores[idx])))
        else:
            if self.doc_vectors is None:
                return []
            q_vec = self.vectorizer.transform([query_plain])
            sims = cosine_similarity(q_vec, self.doc_vectors)[0]
            ranked = np.argsort(sims)[::-1]
            for idx in ranked[:top_k]:
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

    # top keywords method
    def top_keywords(self, doc_id, top_n=10):
        if self.doc_vectors is None:
            return []
        if doc_id < 0 or doc_id >= len(self.doc_vectors):
            return []
        features = None
        try:
            features = self.vectorizer.get_feature_names_out()
        except Exception:
            features = self.vectorizer.get_feature_names()
        vec = self.doc_vectors[doc_id]
        if hasattr(vec, "toarray"):
            arr = np.asarray(vec.todense()).ravel()
        else:
            arr = np.asarray(vec).ravel()
        if arr.sum() == 0:
            return []
        inds = np.argsort(arr)[::-1][:top_n]
        return [f"{features[i]} ({arr[i]:.4f})" for i in inds if arr[i] > 0]

# ----------------------------
# Snippet extraction utility
# ----------------------------
def extract_snippet(doc_text, query_tokens, window=200):
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
    # highlight terms
    for t in set(query_tokens):
        if not t:
            continue
        esc = re.escape(t)
        snippet = re.sub(f"(?i)({esc})", r"<mark>\1</mark>", snippet)
    return snippet

# ----------------------------
# PDF Highlighting (download)
# ----------------------------
def highlight_pdf_bytes(original_path, query_terms):
    """
    Return BytesIO with highlights added. query_terms should be token list (lowercased).
    """
    # Try to open PDF safely
    try:
        doc = fitz.open(original_path)
    except Exception as e:
        # try reading as stream
        with open(original_path, "rb") as fh:
            data = fh.read()
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as e2:
            raise Exception(f"Could not open PDF for highlighting: {e} / {e2}")

    query_terms = [t.lower() for t in query_terms if t]
    for page in doc:
        try:
            page_text = page.get_text("text").lower()
        except Exception:
            page_text = ""
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
                        # ignore individual annotation failures
                        pass
            except Exception:
                # ignore search errors for this term/page
                pass
    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True)
    out.seek(0)
    doc.close()
    return out

# ----------------------------
# PDF Export helpers (FPDF safe)
# ----------------------------
def normalize_text_for_pdf(text):
    if text is None:
        return ""
    replacements = {
        '\u2013': '-', '\u2014': '-', '\u2015': '-',
        '\u2212': '-', '\u2022': '*', '\u00A0': ' '
    }
    for a,b in replacements.items():
        text = text.replace(a,b)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    return str(text)

def safe_wrap_long_tokens(text, max_len=60):
    parts = []
    for word in str(text).split():
        if len(word) > max_len:
            for i in range(0, len(word), max_len):
                parts.append(word[i:i+max_len])
        else:
            parts.append(word)
    return " ".join(parts)

def chunk_text(text, max_chars=800):
    text = str(text)
    if not text:
        return []
    start = 0
    L = len(text)
    chunks = []
    while start < L:
        end = min(L, start + max_chars)
        if end < L:
            seg = text[start:end]
            last_space = seg.rfind(" ")
            if last_space > int(max_chars * 0.4):
                end = start + last_space
        chunks.append(text[start:end].strip())
        start = end
    return chunks

def create_search_report_pdf(query, method, results):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # register DejaVu if available for unicode
    font_candidates = ["fonts/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"]
    font_path = None
    for f in font_candidates:
        if os.path.exists(f):
            font_path = f
            break
    base_font = "Arial"
    if font_path:
        try:
            pdf.add_font("DejaVu", "", font_path, uni=True)
            base_font = "DejaVu"
        except Exception:
            base_font = "Arial"

    pdf.set_font(base_font, size=16)
    header_title = normalize_text_for_pdf(f"DocVista — Search Report")
    pdf.multi_cell(0, 8, safe_wrap_long_tokens(header_title))
    pdf.ln(2)
    pdf.set_font(base_font, size=11)
    dashboard = f"Query: {query}\nRanking method: {method.upper()}\nResults: {len(results)}\nGenerated: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    for line in dashboard.split("\n"):
        pdf.multi_cell(0, 6, safe_wrap_long_tokens(line))
    pdf.ln(6)

    # Table-like results
    for i, r in enumerate(results, start=1):
        pdf.set_font(base_font, size=12)
        title = normalize_text_for_pdf(f"{i}. {r['name']} (Score: {r['score']})")
        for ch in chunk_text(safe_wrap_long_tokens(title), max_chars=160):
            pdf.multi_cell(0, 6, ch)
        pdf.set_font(base_font, size=10)
        # TF-IDF keywords
        try:
            kws = engine.top_keywords(r['index'], top_n=8)
        except Exception:
            kws = []
        if kws:
            pdf.multi_cell(0, 5, "Top keywords: " + ", ".join([normalize_text_for_pdf(k) for k in kws]))
        # snippet
        snippet = re.sub(r"<[^>]*>", "", r.get("snippet", ""))
        snippet = normalize_text_for_pdf(snippet)
        for ch in chunk_text(safe_wrap_long_tokens(snippet), max_chars=600):
            pdf.multi_cell(0, 5, ch)
        # percentage representation
        try:
            pct = int(round(float(r['score']) * 100))
            pdf.multi_cell(0, 5, f"Similarity: {pct}%")
        except Exception:
            pass
        pdf.ln(4)

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf

# ----------------------------
# HTML template
# ----------------------------
BASE_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>DocVista — Smart Multi-Format IR Engine</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
:root{--bg:#f5f7fb;--card:#fff;--text:#0b1724;--muted:#5b6978;--accent:#2563eb;--progress:#4caf50;}
[data-theme="dark"]{--bg:#0b1220;--card:#0b1220;--text:#e6eef8;--muted:#9fb0c8;--accent:#60a5fa;--progress:#5dd37e;}
body{background:linear-gradient(180deg,var(--bg),#eef2f7);color:var(--text);font-family:Inter,system-ui,Arial;padding:24px;}
.container{max-width:1100px;margin:0 auto;}
.card-search{background:var(--card);padding:18px;border-radius:12px;box-shadow:0 6px 18px rgba(2,6,23,0.06);}
.result-card{background:var(--card);padding:14px;border-radius:10px;margin-bottom:12px;box-shadow:0 2px 8px rgba(0,0,0,0.06);}
mark{background:var(--accent);color:#032242;padding:0 3px;border-radius:3px;}
.meta{color:var(--muted);font-size:0.9rem;}
.progress-bar{height:10px;background:#ddd;border-radius:10px;overflow:hidden;}
.progress{height:100%;background:var(--progress);width:0;transition:width 0.8s;}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);align-items:center;justify-content:center;}
.modal-card{background:var(--card);padding:18px;border-radius:8px;max-width:480px;}
.upload-box{background:var(--card);padding:14px;border-radius:8px;margin-top:12px;}
.footer-small{color:var(--muted);margin-top:18px;text-align:center;}
</style>
</head>
<body data-theme="light">
<div class="container">
  <div class="card-search mb-3">
    <div class="d-flex justify-content-between align-items-start">
      <div>
        <h3 class="mb-0">DocVista</h3>
        <div class="meta">Search PDFs, DOCX, TXT • Choose TF–IDF or BM25 • Export & Highlight</div>
      </div>
      <div class="d-flex gap-2 align-items-center">
        <button id="themeToggle" class="btn btn-sm btn-outline-secondary">🌙</button>
        <a class="btn btn-sm btn-outline-primary" href="/bm25">BM25 Info</a>
        <a class="btn btn-sm btn-outline-secondary" href="/refresh">Reload</a>
      </div>
    </div>

    <form id="searchForm" method="POST" action="/" class="row g-2 mt-3 align-items-center">
      <div class="col-md-8 col-12">
        <input id="queryInput" name="query" class="form-control form-control-lg" placeholder="Enter search query (e.g. deadlock, cpu scheduling)" required />
      </div>
      <div class="col-md-2 col-6">
        <select name="method" class="form-select form-select-lg">
          <option value="tfidf">TF–IDF</option>
          <option value="bm25">BM25</option>
        </select>
      </div>
      <div class="col-md-1 col-3">
        <button class="btn btn-primary btn-lg w-100">Search</button>
      </div>
      <div class="col-md-1 col-3">
        <button id="clearBtn" type="button" class="btn btn-outline-secondary btn-lg w-100">Clear</button>
      </div>
    </form>

    <div class="upload-box mt-3">
      <h6 class="mb-2">Upload New Document</h6>
      <form action="/upload" method="POST" enctype="multipart/form-data" class="d-flex gap-2 align-items-center">
        <input type="file" name="file" accept=".pdf,.docx,.txt" class="form-control form-control-sm" required />
        <button class="btn btn-sm btn-success">Upload</button>
      </form>
      <div class="meta mt-2">Drop files into <code>/documents</code> folder or use Upload. Supported: PDF, DOCX, TXT.</div>
    </div>

    <div class="mt-3 meta">Documents loaded: {{ n_docs }}</div>
  </div>

  {% if results %}
    <div class="mb-3 d-flex justify-content-between align-items-center">
      <div><strong>Query:</strong> "{{ query }}"</div>
      <div>
        <form method="POST" action="/export" style="display:inline;">
          <input type="hidden" name="query" value="{{ query }}">
          <input type="hidden" name="method" value="{{ method }}">
          <button class="btn btn-sm btn-outline-secondary">📥 Download Full Report (PDF)</button>
        </form>
      </div>
    </div>

    <div id="resultsArea">
      {% for r in results %}
        <div class="result-card">
          <div class="d-flex justify-content-between">
            <div>
              <h5 class="mb-0">{{ r.name }}</h5>
              <div class="meta">Score: {{ r.score }} • {{ r.score * 100 | round(0) }}%</div>
            </div>
            <div class="text-end">
              <a class="btn btn-sm btn-outline-primary" href="/download/{{ r.index }}">Download</a>
              {% if r.name.lower().endswith('.pdf') %}
                <a class="btn btn-sm btn-outline-warning" href="/highlight/{{ r.index }}/{{ query | urlencode }}/{{ method }}">✨ Highlight & Download</a>
              {% endif %}
              <form method="POST" action="/export" style="display:inline;">
                <input type="hidden" name="query" value="{{ query }}">
                <input type="hidden" name="method" value="{{ method }}">
                <input type="hidden" name="single" value="{{ r.index }}">
                <button class="btn btn-sm btn-primary">📄 Export This Document</button>
              </form>
            </div>
          </div>

          <div class="snippet mt-2">{{ r.snippet | safe }}</div>

          <div class="mt-3">
            <div class="progress-bar"><div class="progress" style="width: {{ r.score * 100 }}%;"></div></div>
          </div>

          <div class="mt-2">
            <a href="#" onclick="openKeywords({{ r.index }}); return false;">🔍 View TF–IDF Keywords</a>
          </div>
        </div>
      {% endfor %}
    </div>
  {% endif %}

  <div class="footer-small">DocVista — built for IR microproject • Multi-format • TF–IDF & BM25 • Export & PDF highlight</div>
</div>

<!-- Keyword modal -->
<div id="modalBg" class="modal-bg d-flex">
  <div class="modal-card">
    <div class="d-flex justify-content-between align-items-start">
      <h5>Top TF–IDF Keywords</h5>
      <button class="btn btn-sm btn-outline-secondary" onclick="closeModal()">Close</button>
    </div>
    <ul id="keywordList" class="mt-2"></ul>
  </div>
</div>

<script>
// theme
const themeBtn = document.getElementById("themeToggle");
const savedTheme = localStorage.getItem("docvista_theme") || "light";
document.body.setAttribute("data-theme", savedTheme);
themeBtn.textContent = savedTheme === "dark" ? "☀️" : "🌙";
themeBtn.onclick = () => {
  const cur = document.body.getAttribute("data-theme") || "light";
  const nxt = cur === "dark" ? "light" : "dark";
  document.body.setAttribute("data-theme", nxt);
  themeBtn.textContent = nxt === "dark" ? "☀️" : "🌙";
  localStorage.setItem("docvista_theme", nxt);
};

// clear
document.getElementById("clearBtn").addEventListener("click", ()=>{
  document.getElementById("queryInput").value = "";
  document.getElementById("queryInput").focus();
});

// results animation
window.addEventListener("DOMContentLoaded", ()=>{
  document.querySelectorAll(".result-card").forEach((el,i)=>{
    setTimeout(()=> el.classList.add("show"), i*120);
  });
});

// search history
function loadHistory(){
  let h = JSON.parse(localStorage.getItem("docvista_history") || "[]");
  const list = document.getElementById("historyList");
  if (!list) return;
  list.innerHTML = "";
  h.slice(-10).reverse().forEach(q => { list.innerHTML += `<li>${q}</li>`; });
}
loadHistory();
document.getElementById("searchForm").onsubmit = () => {
  const q = document.getElementById("queryInput").value.trim();
  if (!q) return;
  let h = JSON.parse(localStorage.getItem("docvista_history") || "[]");
  h.push(q);
  h = [...new Set(h)]; // unique
  if (h.length > 50) h = h.slice(-50);
  localStorage.setItem("docvista_history", JSON.stringify(h));
};

// modal keywords
function openKeywords(idx){
  fetch(`/keywords/${idx}`).then(r => r.json()).then(data => {
    const box = document.getElementById("keywordList");
    box.innerHTML = "";
    if (Array.isArray(data)){
      data.forEach(k => box.innerHTML += `<li>${k}</li>`);
    } else if (data.error){
      box.innerHTML = `<li>Error: ${data.error}</li>`;
    }
    document.getElementById("modalBg").style.display = "flex";
  });
}
function closeModal(){ document.getElementById("modalBg").style.display = "none"; }
</script>
</body>
</html>
"""

# ----------------------------
# Routes
# ----------------------------
engine = IREngine()

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
    return render_template_string(BASE_HTML, results=results, n_docs=len(engine.doc_names), query=query, method=method)

@app.route("/refresh")
def refresh():
    engine.refresh()
    return redirect(url_for("home"))

@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f:
        return "<h3>No file uploaded</h3><a href='/'>Back</a>"
    filename = secure_filename(f.filename)
    if not filename.lower().endswith(ALLOWED_EXT):
        return "<h3>Only PDF, DOCX, TXT allowed</h3><a href='/'>Back</a>"
    save_path = os.path.join(DOCS_FOLDER, filename)
    f.save(save_path)
    engine.refresh()
    return f"<h3>Uploaded: {filename}</h3><a href='/'>Back to search</a>"

@app.route("/download/<int:idx>")
def download_doc(idx):
    if idx < 0 or idx >= len(engine.doc_paths):
        return "Invalid document", 404
    path = engine.doc_paths[idx]
    name = engine.doc_names[idx]
    # If it's a PDF, send the original PDF file
    try:
        if path.lower().endswith(".pdf"):
            return send_file(path, as_attachment=True, download_name=name, mimetype="application/pdf")
        else:
            # send as text file
            text = engine.docs_raw[idx]
            buf = io.BytesIO()
            buf.write(text.encode("utf-8", errors="ignore"))
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
    # idx - document index, query - urlencoded, method ignored here
    if idx < 0 or idx >= len(engine.doc_paths):
        return "Invalid document", 404
    path = engine.doc_paths[idx]
    if not path.lower().endswith(".pdf"):
        return "<h3>Highlighting only supported for PDF files.</h3><a href='/'>Back</a>"
    query_decoded = unquote_plus(query)
    q_tokens = normalize_for_index(preprocess(query_decoded)).split()
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
    if single is not None:
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
    <h2>BM25 — Explanation</h2>
    <p>BM25 is a ranking function used in search engines. Formula:</p>
    <pre>
score(D,Q) = Σ idf(t) * (f(t,D) * (k1+1)) / (f(t,D) + k1*(1-b+b*|D|/avgdl))
    </pre>
    <a href="/">Back</a>
    """
    return html

# ----------------------------
# Run
# ----------------------------
if __name__ == "__main__":
    print("Loading documents from:", os.path.abspath(DOCS_FOLDER))
    print("Starting DocVista on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
