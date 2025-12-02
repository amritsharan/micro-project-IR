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
            try:
                q_vec = self.vectorizer.transform([query_plain])
                sims = cosine_similarity(q_vec, self.doc_vectors)[0]
            except Exception:
                if self.bm25:
                    scores = self.bm25.score(q_tokens)
                    ranked = np.argsort(scores)[::-1]
                    for idx in ranked[:top_k]:
                        results.append((idx, float(scores[idx])))
                else:
                    return []
            else:
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
    replacements = {
        '\u2013': '-', '\u2014': '-', '\u2015': '-',
        '\u2212': '-', '\u2022': '*', '\u00A0': ' '
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    # remove C category characters
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    return str(text)

def safe_wrap_long_tokens(text, max_len=40):
    """
    Insert zero-width spaces inside very long tokens to let FPDF wrap them.
    """
    if not text:
        return ""
    # sanitize and remove control characters except newline
    text = text.replace("\t", " ").replace("\r", " ")
    text = ''.join(ch for ch in text if ord(ch) >= 32 or ch == '\n')
    words = text.split(" ")
    wrapped = []
    for w in words:
        if len(w) <= max_len:
            wrapped.append(w)
        else:
            parts = [w[i:i+max_len] for i in range(0, len(w), max_len)]
            wrapped.append("\u200b".join(parts))
    return " ".join(wrapped)

def force_break_long_tokens(text, max_len=80):
    """
    Breaks tokens longer than max_len into hard chunks separated by spaces.
    This is last-resort to prevent FPDF from failing.
    """
    if not text:
        return ""
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
    # strip zero width weirdness, keep printable
    line = str(line)
    line = line.replace("\t", " ").replace("\r", " ")
    line = ''.join(ch for ch in line if ord(ch) >= 32)
    return line

def chunk_text_final(text, size):
    """break a string into final safe chunks"""
    if not text:
        return []
    text = str(text)
    return [text[i:i+size] for i in range(0, len(text), size)]

def create_search_report_pdf(query, method, results):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Try DejaVu for unicode; fallback to Arial
    font_candidates = ["fonts/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"]
    base_font = "Arial"
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                pdf.add_font("DejaVu", "", fp, uni=True)
                base_font = "DejaVu"
                break
            except Exception:
                base_font = "Arial"

    # Title
    pdf.set_font(base_font, size=16)
    title = normalize_text_for_pdf("DocVista — Search Report")
    safe = safe_wrap_long_tokens(clean_line_for_pdf(title), max_len=40)
    safe = force_break_long_tokens(safe, max_len=200)
    try:
        pdf.multi_cell(0, 8, safe)
    except Exception:
        for ch in chunk_text_final(safe, 120):
            pdf.multi_cell(0, 8, ch)

    pdf.ln(3)
    pdf.set_font(base_font, size=11)
    dashboard = f"Query: {query}\nMethod: {method}\nResults: {len(results)}\nGenerated: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    for line in dashboard.split("\n"):
        l = normalize_text_for_pdf(line)
        l = safe_wrap_long_tokens(l, max_len=40)
        l = force_break_long_tokens(l, max_len=200)
        try:
            pdf.multi_cell(0, 6, l)
        except Exception:
            for ch in chunk_text_final(l, 120):
                pdf.multi_cell(0, 6, ch)
    pdf.ln(6)

    # Results
    for i, r in enumerate(results, start=1):
        pdf.set_font(base_font, size=12)
        title = f"{i}. {r['name']} (Score: {r['score']})"
        t = normalize_text_for_pdf(title)
        t = safe_wrap_long_tokens(t, max_len=40)
        t = force_break_long_tokens(t, max_len=200)
        for chunk in chunk_text_final(t, 160):
            pdf.multi_cell(0, 6, chunk)

        pdf.set_font(base_font, size=10)
        try:
            kws = engine.top_keywords(r["index"], top_n=8)
        except Exception:
            kws = []
        if kws:
            kw_line = "Top keywords: " + ", ".join(kws)
            kw_line = normalize_text_for_pdf(kw_line)
            kw_line = safe_wrap_long_tokens(kw_line, max_len=40)
            kw_line = force_break_long_tokens(kw_line, max_len=200)
            try:
                pdf.multi_cell(0, 5, kw_line)
            except Exception:
                for ch in chunk_text_final(kw_line, 120):
                    pdf.multi_cell(0, 5, ch)

        # Snippet
        try:
            pdf.multi_cell(0, 5, "Snippet:")
        except Exception:
            pass

        snippet = re.sub(r"<[^>]*>", "", r.get("snippet", ""))
        snippet = normalize_text_for_pdf(snippet)
        snippet = safe_wrap_long_tokens(snippet, max_len=40)
        snippet = force_break_long_tokens(snippet, max_len=200)
        try:
            for ch in chunk_text_final(snippet, 600):
                pdf.multi_cell(0, 5, ch)
        except Exception:
            # final fallback per-character
            for ch in chunk_text_final(snippet, 120):
                pdf.multi_cell(0, 5, ch)
        pdf.ln(4)

    # Build bytes safely
    s = pdf.output(dest='S')
    b = s.encode('latin-1', 'replace')
    buf = io.BytesIO(b)
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
<title>DocVista — Smart IR</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#f4f6f9; --card:#ffffff; --muted:#6b7280; --accent:#0f62fe; --accent-2:#0066cc;
}
body{font-family:Inter,system-ui,Arial,Helvetica,sans-serif;background:var(--bg); color:#0b1724; padding:24px;}
.container{max-width:1200px;margin:0 auto;}
.header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px;}
.brand{display:flex;gap:12px;align-items:center;}
.logo{width:46px;height:46px;border-radius:10px;background:linear-gradient(135deg,var(--accent),var(--accent-2));display:flex;align-items:center;justify-content:center;color:white;font-weight:700;}
.card{background:var(--card);border-radius:12px;padding:18px;box-shadow:0 6px 18px rgba(15,22,40,0.06);}
.search-row{display:flex;gap:12px;align-items:center;}
.input-large{flex:1;}
.meta{color:var(--muted);font-size:0.9rem;}
.upload-box{margin-top:12px;}
.results{margin-top:18px;}
.result-card{border-radius:10px;padding:14px;margin-bottom:12px;background:linear-gradient(180deg,#fff,#fbfdff);box-shadow:0 3px 10px rgba(12,20,40,0.04);display:flex;justify-content:space-between;gap:12px;}
.result-left{flex:1;}
.result-right{text-align:right;min-width:220px;}
.snippet{color:#0b1724;margin-top:8px;}
.kws{margin-top:8px;color:var(--muted);font-size:0.9rem;}
.footer{margin-top:18px;color:var(--muted);font-size:0.9rem;text-align:center;}
.small-btn{padding:6px 10px;font-size:0.9rem;border-radius:8px;}
.progress-bar{height:8px;background:#eef2ff;border-radius:8px;overflow:hidden;}
.progress{height:100%;background:linear-gradient(90deg,#4caf50,#2ea44f);width:0;transition:width 0.9s;}
/* responsive tweaks */
@media (max-width:800px){
  .result-right{min-width:120px;text-align:left;}
  .search-row{flex-direction:column;align-items:stretch;}
}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="brand">
      <div class="logo">DV</div>
      <div>
        <h3 style="margin:0">DocVista</h3>
        <div class="meta">Material · Professional · Export & Highlight</div>
      </div>
    </div>
    <div style="text-align:right">
      <a class="btn btn-outline-secondary btn-sm" href="/bm25">BM25 Info</a>
      <a class="btn btn-outline-secondary btn-sm" href="/refresh">Reload</a>
    </div>
  </div>

  <div class="card">
    <form id="searchForm" method="POST" action="/" enctype="multipart/form-data" class="row g-2 align-items-center">
      <div class="col-12 col-md-7">
        <input id="queryInput" name="query" class="form-control form-control-lg input-large" placeholder="Search your documents — try 'deadlock' or 'cpu scheduling'" required />
      </div>
      <div class="col-12 col-md-2">
        <select name="method" class="form-select form-select-lg">
          <option value="tfidf">TF–IDF</option>
          <option value="bm25">BM25</option>
        </select>
      </div>
      <div class="col-6 col-md-1">
        <button class="btn btn-primary btn-lg w-100">Search</button>
      </div>
      <div class="col-6 col-md-2 d-flex gap-2">
        <input type="file" name="file" accept=".pdf,.docx,.txt" class="form-control form-control-sm" />
        <button name="upload" value="1" class="btn btn-success">Upload</button>
      </div>
    </form>

    <div class="upload-box meta">Upload supported: PDF · DOCX · TXT • Or drop files in <code>/documents</code></div>
  </div>

  {% if results %}
  <div class="results">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <div><strong>Query:</strong> "{{ query }}" • <span class="meta">Documents: {{ n_docs }}</span></div>
      <div>
        <form method="POST" action="/export" style="display:inline;">
          <input type="hidden" name="query" value="{{ query }}">
          <input type="hidden" name="method" value="{{ method }}">
          <button class="btn btn-outline-primary small-btn">📥 Download Full Report</button>
        </form>
      </div>
    </div>

    {% for r in results %}
    <div class="result-card">
      <div class="result-left">
        <h5 style="margin:0">{{ r.name }}</h5>
        <div class="meta">Score: {{ r.score }} • {{ (r.score * 100)|round(0) }}%</div>
        <div class="snippet">{{ r.snippet | safe }}</div>
        <div class="kws">
          <a href="#" class="view-kws" data-idx="{{ r.index }}">🔍 View TF–IDF keywords</a>
          <div id="kws-{{ r.index }}" style="display:none;margin-top:8px;"></div>
        </div>
      </div>
      <div class="result-right">
        <div class="mb-2">
          <a class="btn btn-outline-secondary btn-sm" href="/download/{{ r.index }}">Download</a>
          {% if r.name.lower().endswith('.pdf') %}
          <a class="btn btn-warning btn-sm" href="/highlight/{{ r.index }}/{{ query | urlencode }}/{{ method }}">✨ Highlight & Download</a>
          {% endif %}
        </div>
        <div style="margin-top:10px">
          <div class="progress-bar">
            <div class="progress" style="width: {{ (r.score * 100)|round(0) }}%"></div>
          </div>
        </div>
        <div class="meta" style="margin-top:8px">
          <form method="POST" action="/export" style="display:inline;">
            <input type="hidden" name="query" value="{{ query }}">
            <input type="hidden" name="method" value="{{ method }}">
            <input type="hidden" name="single" value="{{ r.index }}">
            <button class="btn btn-primary btn-sm">📄 Export This</button>
          </form>
        </div>
      </div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <div class="footer">DocVista · Built for IR projects — TF–IDF, BM25, export, highlight.</div>
</div>

<script>
document.addEventListener('click', function(e){
  if (e.target && e.target.classList.contains('view-kws')){
    e.preventDefault();
    const idx = e.target.dataset.idx;
    const box = document.getElementById('kws-' + idx);
    if (!box) return;
    if (box.style.display === 'block') { box.style.display = 'none'; return; }
    box.innerHTML = 'Loading...';
    fetch('/keywords/' + idx).then(r => r.json()).then(js => {
      if (Array.isArray(js)){
        box.innerHTML = '<div style="padding:8px;background:#f7f9ff;border-radius:6px;">' + js.join(', ') + '</div>';
      } else {
        box.innerHTML = '<div style="color:#b00">Error fetching keywords</div>';
      }
      box.style.display = 'block';
    }).catch(_=>{ box.innerHTML = '<div style="color:#b00">Error</div>'; box.style.display='block';});
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
    if request.method == "POST":
        # upload handling: only when upload button submitted
        if request.form.get("upload") == "1":
            f = request.files.get("file")
            if f:
                fn = secure_filename(f.filename)
                if fn and fn.lower().endswith(ALLOWED_EXT):
                    path = os.path.join(DOCS_FOLDER, fn)
                    f.save(path)
                    engine.refresh()
        # search handling (if query provided)
        query = request.form.get("query", "").strip()
        method = request.form.get("method", "tfidf")
        if query:
            results = engine.search(query, method=method, top_k=20)
    return render_template_string(BASE_HTML, results=results, n_docs=len(engine.doc_names), query=query, method=method)

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
    <div style="padding:20px;">
      <h3>BM25 — Short Explanation</h3>
      <p>BM25 is a widely used ranking function in information retrieval. Formula:</p>
      <pre>score(D,Q) = Σ idf(t) * (f(t,D)*(k1+1)) / (f(t,D) + k1*(1-b+b*|D|/avgdl))</pre>
      <a href="/">Back</a>
    </div>
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
