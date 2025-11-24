# engine.py
import os
import io
import re
import string
from math import log
from pathlib import Path
from fpdf import FPDF
from fpdf.errors import FPDFException
from flask import Flask, request, render_template_string, send_file, redirect, url_for
from werkzeug.utils import secure_filename
import docx
import PyPDF2
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ----------------------------
# Configuration
# ----------------------------
DOCS_FOLDER = "documents"            # put your PDFs/DOCXs/TXTs here
# developer-provided uploaded file path (from your environment)
UPLOADED_SAMPLE_PATH = "/mnt/data/Screenshot (944).png"
ALLOWED_EXT = (".txt", ".pdf", ".docx")

# Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB max upload

# ----------------------------
# Utilities: extraction + preprocess
# ----------------------------
def extract_text_from_pdf(path):
    text = ""
    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for p in reader.pages:
                page_text = p.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        pass
    return text

def extract_text_from_docx(path):
    try:
        doc = docx.Document(path)
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception:
        return ""

def extract_text_from_txt(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def preprocess(text):
    # keep whitespace for snippet extraction, normalize newlines
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def normalize_for_index(text):
    # lower + remove punctuation for token-level models
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return text

# ----------------------------
# Load documents (any supported type)
# ----------------------------
def load_documents(folder=DOCS_FOLDER):
    docs_raw = []
    doc_names = []
    doc_paths = []

    os.makedirs(folder, exist_ok=True)
    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(ALLOWED_EXT):
            continue
        path = os.path.join(folder, fname)
        if fname.lower().endswith(".pdf"):
            raw = extract_text_from_pdf(path)
        elif fname.lower().endswith(".docx"):
            raw = extract_text_from_docx(path)
        else:
            raw = extract_text_from_txt(path)

        raw = preprocess(raw)
        if raw and len(raw) > 10:
            docs_raw.append(raw)
            doc_names.append(fname)
            doc_paths.append(path)

    return docs_raw, doc_names, doc_paths

# ----------------------------
# BM25 implementation (simple)
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
            for word in doc:
                freqs[word] = freqs.get(word, 0) + 1
            self.doc_freqs.append(freqs)
            for w in freqs.keys():
                self.df[w] = self.df.get(w, 0) + 1

        # precompute idf
        self.idf = {}
        for w, freq in self.df.items():
            # typical BM25 idf smoothing
            self.idf[w] = log(1 + (self.N - freq + 0.5) / (freq + 0.5))

        # parameters
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
# Build indices at startup (can be refreshed via UI)
# ----------------------------
class IREngine:
    def __init__(self):
        self.docs_raw, self.doc_names, self.doc_paths = load_documents(DOCS_FOLDER)
        self._build()

    def _build(self):
        # TF-IDF
        self.vectorizer = TfidfVectorizer(stop_words="english")
        if self.docs_raw:
            self.doc_vectors = self.vectorizer.fit_transform(self.docs_raw)
        else:
            self.doc_vectors = None

        # BM25 tokens
        self.docs_tokens = [normalize_for_index(d).split() for d in self.docs_raw]
        if self.docs_tokens:
            self.bm25 = BM25Simple(self.docs_tokens)
        else:
            self.bm25 = None

    def refresh(self):
        self.docs_raw, self.doc_names, self.doc_paths = load_documents(DOCS_FOLDER)
        self._build()

    def search(self, query, method="tfidf", top_k=5):
        query_plain = preprocess(query)
        query_norm = normalize_for_index(query_plain)
        q_tokens = [t for t in query_norm.split() if t]

        results = []
        if method.lower() == "bm25" and self.bm25 is not None:
            scores = self.bm25.score(q_tokens)
            ranked = np.argsort(scores)[::-1]
            for idx in ranked[:top_k]:
                results.append((idx, float(scores[idx])))
        else:
            # default TF-IDF (safe fallback)
            if self.doc_vectors is None:
                return []
            q_vec = self.vectorizer.transform([query_plain])
            sims = cosine_similarity(q_vec, self.doc_vectors)[0]
            ranked = np.argsort(sims)[::-1]
            for idx in ranked[:top_k]:
                results.append((idx, float(sims[idx])))

        # attach snippet
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

# ----------------------------
# Snippet extraction + highlight
# ----------------------------
def extract_snippet(doc_text, query_tokens, window=200):
    lower = doc_text.lower()
    best_pos = -1
    for token in query_tokens:
        pos = lower.find(token)
        if pos != -1:
            best_pos = pos
            break
    if best_pos == -1:
        # fallback: return the first window chars
        snippet = (doc_text[:window] + "...") if len(doc_text) > window else doc_text
        # highlight query tokens even if not found
        for t in set(query_tokens):
            if not t:
                continue
            esc = re.escape(t)
            snippet = re.sub(f"(?i)({esc})", r"<mark>\1</mark>", snippet)
        return snippet
    start = max(0, best_pos - window // 2)
    end = min(len(doc_text), start + window)
    snippet = doc_text[start:end]
    # highlight tokens (HTML)
    for t in set(query_tokens):
        if not t:
            continue
        esc = re.escape(t)
        snippet = re.sub(f"(?i)({esc})", r"<mark>\1</mark>", snippet)
    if start > 0:
        snippet = "..." + snippet
    if end < len(doc_text):
        snippet = snippet + "..."
    return snippet

# ----------------------------
# Initialize engine
# ----------------------------
engine = IREngine()

# ----------------------------
# PDF Export (UTF-8-safe using fpdf2 and DejaVu font)
# ----------------------------
import unicodedata

def normalize_text(text):
    """Remove/replace unicode chars unsupported by FPDF."""
    # Convert fancy punctuation to basic
    replacements = {
        '\u2013': '-',  # en dash
        '\u2014': '-',  # em dash
        '\u2015': '-',  # horizontal bar
        '\u2212': '-',  # minus sign
        '\u2022': '*',  # bullet
        '\u00A0': ' ',  # non-breaking space
    }

    for bad, good in replacements.items():
        text = text.replace(bad, good)

    # Remove control characters
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")

    # Optionally strip remaining non-Latin1 (to be safe)
    try:
        text = text.encode("latin-1", "ignore").decode("latin-1")
    except Exception:
        # fallback: keep original but later safe_wrap will handle long tokens
        pass

    return text

def safe_wrap(text, max_len=40):
    """Break very long words (like URLs, big tokens) so FPDF won't crash."""
    words = text.split()
    wrapped = []

    for w in words:
        if len(w) > max_len:
            parts = [w[i:i+max_len] for i in range(0, len(w), max_len)]
            wrapped.extend(parts)
        else:
            wrapped.append(w)

    return " ".join(wrapped)

def prepare_pdf_text(text):
    """Full cleaning pipeline."""
    text = normalize_text(text)
    text = safe_wrap(text, max_len=40)
    return text

def _chunks_of(text, max_chars=800):
    """Yield chunks of text with <= max_chars characters, breaking at whitespace when possible."""
    if not text:
        return
    start = 0
    L = len(text)
    while start < L:
        end = min(L, start + max_chars)
        # try to break at last whitespace between start and end
        if end < L:
            seg = text[start:end]
            last_space = seg.rfind(" ")
            if last_space > max(0, int(max_chars*0.6)):
                end = start + last_space
        yield text[start:end].strip()
        start = end

def create_pdf_bytes(query, method, results):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # search for DejaVu font
    font_path = None
    for candidate in [
        "fonts/DejaVuSans.ttf",
        "fonts/ttf/DejaVuSans.ttf",
        "DejaVuSans.ttf",
        "fonts/DejaVuSans.ttf"
    ]:
        if os.path.exists(candidate):
            font_path = candidate
            break

    # register font
    if font_path:
        try:
            pdf.add_font("DejaVu", "", font_path, uni=True)
            base_font = "DejaVu"
        except Exception:
            base_font = "Arial"
    else:
        base_font = "Arial"

    # width constant to avoid FPDFException
    CELL_WIDTH = 180  # safe width inside A4 after margins

    # Title
    pdf.set_font(base_font, size=14)
    title = prepare_pdf_text(f"Search Report — Query: {query}")
    pdf.multi_cell(CELL_WIDTH, 8, title)
    pdf.ln(3)

    # Header
    pdf.set_font(base_font, size=11)
    header = prepare_pdf_text(f"Ranking Method: {method.upper()}")
    pdf.multi_cell(CELL_WIDTH, 6, header)
    pdf.ln(4)

    # Results
    for r in results:
        # Document name + score
        pdf.set_font(base_font, size=12)
        line = prepare_pdf_text(f"{r['name']} (Score: {r['score']})")
        pdf.multi_cell(CELL_WIDTH, 6, line)

        # Snippet
        pdf.set_font(base_font, size=10)
        snippet_text = re.sub(r"<[^>]*>", "", r["snippet"])
        snippet_text = prepare_pdf_text(snippet_text)

        # safest write
        for chunk in _chunks_of(snippet_text, max_chars=500):
            safe_chunk = prepare_pdf_text(chunk)
            pdf.multi_cell(CELL_WIDTH, 5, safe_chunk)

        pdf.ln(2)

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf


# ----------------------------
# Flask templates (single-file) - improved UI
# ----------------------------
BASE_HTML = """
<!doctype html>
<html lang="en" data theme="dark">
<head>
  <meta charset="utf-8">
  <title>Mini IR Engine — Modern UI</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    :root{
      --bg:#0f1724;
      --card:#0b1220;
      --text:#e6eef8;
      --muted:#9fb0c8;
      --accent:#60a5fa;
    }
    [data-theme="light"]{
      --bg:#f5f7fb;
      --card:#ffffff;
      --text:#0b1724;
      --muted:#5b6978;
      --accent:#2563eb;
    }
    body { background: linear-gradient(180deg, rgba(10,12,20,1) 0%, rgba(18,24,33,1) 100%); color:var(--text); transition: background .4s ease, color .3s ease; font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial; }
    [data-theme="light"] body { background: linear-gradient(180deg,#f8fafc,#eef2f7); }
    .container { max-width:1100px; margin-top:28px; }
    .card-search { padding:18px; border-radius:12px; background:linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)); backdrop-filter: blur(6px); box-shadow: 0 6px 18px rgba(2,6,23,0.6); transition: transform .25s ease; }
    [data-theme="light"] .card-search { box-shadow: 0 6px 18px rgba(16,24,40,0.06); }
    .result { margin-bottom:12px; padding:16px; border-radius:10px; background:var(--card); box-shadow: 0 4px 14px rgba(2,6,23,0.45); transition: transform .18s ease, box-shadow .18s ease, opacity .4s ease; opacity:0; transform: translateY(6px); }
    .result.show { opacity:1; transform:none; }
    .result:hover { transform: translateY(-4px); box-shadow: 0 8px 30px rgba(2,6,23,0.6); }
    mark { background: var(--accent); color: #032242; padding:0 2px; border-radius:4px; }
    .meta { font-size:.85rem; color:var(--muted); }
    .snippet { margin-top:8px; color:var(--text); }
    .controls { display:flex; gap:8px; align-items:center; }
    .btn-ghost { background: transparent; border:1px solid rgba(255,255,255,0.06); color:var(--text); }
    [data-theme="light"] .btn-ghost { border-color: rgba(2,6,23,0.06); }
    .toggle { cursor:pointer; padding:6px 10px; border-radius:999px; border:1px solid rgba(255,255,255,0.06); background:transparent; color:var(--text); }
    .download-btn { margin-left:6px; }
    footer { margin-top:28px; text-align:center; color:var(--muted); }
    @media (max-width:768px){
      .controls { flex-direction: column; align-items: stretch; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="card card-search mb-4">
      <div class="d-flex justify-content-between align-items-start">
        <div>
          <h3 class="mb-0">Mini IR Engine</h3>
          <div class="meta">Search across your documents — PDF / DOCX / TXT · Choose TF-IDF or BM25 · Animated UI</div>
        </div>
        <div class="d-flex gap-2 align-items-center">
          <button id="themeToggle" class="toggle" title="Toggle theme">🌙</button>
          <a class="btn btn-sm btn-outline-light" href="/upload">Upload</a>
          <a class="btn btn-sm btn-light" href="/refresh">Reload</a>
          <a class="btn btn-sm btn-link text-decoration-none" href="/sample" target="_blank">View sample</a>
        </div>
      </div>

      <form id="searchForm" method="POST" action="/search" class="row gy-2 gx-2 align-items-center mt-3">
        <div class="col-md-8 col-12">
          <input id="queryInput" name="query" class="form-control form-control-lg" placeholder="Search (e.g., deadlock, cpu scheduling, machine learning)" autocomplete="off" required />
        </div>
        <div class="col-md-2 col-6">
          <select name="method" class="form-select form-select-lg">
            <option value="tfidf">TF–IDF</option>
            <option value="bm25">BM25</option>
          </select>
        </div>
        <div class="col-md-1 col-3 d-grid">
          <button class="btn btn-primary btn-lg">Search</button>
        </div>
        <div class="col-md-1 col-3 d-grid">
          <button id="clearBtn" type="button" class="btn btn-outline-secondary btn-lg">Clear</button>
        </div>
      </form>

      <div class="mt-3 meta">Documents loaded: {{n_docs}} · Try queries like <code>deadlock</code>, <code>cpu scheduling</code></div>
    </div>

    <div id="resultsArea">
      {% if results %}
        <div class="mb-3 d-flex justify-content-between align-items-center">
          <div><strong>Query:</strong> "{{query}}"</div>
          <div>
            <form method="POST" action="/export" style="display:inline;">
              <input type="hidden" name="query" value="{{query}}">
              <input type="hidden" name="method" value="{{method}}">
              <button class="btn btn-sm btn-outline-secondary">Export Full Report (PDF)</button>
            </form>
          </div>
        </div>

        {% for r in results %}
          <div class="result card-body show" id="res-{{r.index}}">
            <div class="d-flex justify-content-between align-items-start">
              <div>
                <a href="/view/{{r.index}}" target="_blank" style="text-decoration:none;"><h5 class="mb-1">{{r.name}}</h5></a>
                <div class="meta">Score: {{r.score}}</div>
              </div>
              <div class="text-end">
                <a class="btn btn-sm btn-outline-light" href="/download/{{r.index}}">Download</a>
                <form method="POST" action="/export" style="display:inline;">
                  <input type="hidden" name="query" value="{{query}}">
                  <input type="hidden" name="method" value="{{method}}">
                  <input type="hidden" name="single" value="{{r.index}}">
                  <button class="btn btn-sm btn-primary download-btn">Export (PDF)</button>
                </form>
              </div>
            </div>
            <div class="snippet mt-2">{{ r.snippet | safe }}</div>
          </div>
        {% endfor %}
      {% endif %}

      {% if not results and query_provided %}
        <div class="alert alert-warning">No documents matched your query. Try different words or add more files in the <code>documents/</code> folder.</div>
      {% endif %}
    </div>

    <footer>
      <small>Single-file Flask • Modern UI • Dark/Light toggle • Animated results</small>
    </footer>
  </div>

  <script>
  // ========================
  // THEME TOGGLE (Light/Dark)
  // ========================
  const btn = document.getElementById('themeToggle');

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    btn.textContent = theme === 'dark' ? '🌙' : '☀️';
  }

  // load previous theme or default to dark
  const savedTheme = localStorage.getItem('ir_theme') || 'dark';
  applyTheme(savedTheme);

  // toggle theme
  btn.onclick = () => {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    localStorage.setItem('ir_theme', next);
  };

  // ============================
  // ANIMATED RESULTS (no vanish)
  // ============================
  document.addEventListener('DOMContentLoaded', () => {
    const items = document.querySelectorAll('.result');
    items.forEach((el, i) => {
      setTimeout(() => {
        el.classList.add('show');
      }, 80 * i);
    });
  });

  // ========================
  // CLEAR INPUT BUTTON
  // ========================
  document.getElementById('clearBtn').addEventListener('click', () => {
    const q = document.getElementById('queryInput');
    q.value = '';
    q.focus();
  });
</script>
</body>
</html>
"""

# ----------------------------
# Flask routes
# ----------------------------
@app.route("/", methods=["GET"])
def home():
    return render_template_string(BASE_HTML, results=None, n_docs=len(engine.docs_raw), query_provided=False)

@app.route("/search", methods=["POST"])
def search():
    q = request.form.get("query", "").strip()
    method = request.form.get("method", "tfidf")
    if not q:
        return redirect(url_for("home"))
    results = engine.search(q, method=method, top_k=10)
    return render_template_string(BASE_HTML, results=results, n_docs=len(engine.docs_raw), query=q, method=method, query_provided=True)

@app.route("/refresh", methods=["GET"])
def refresh():
    engine.refresh()
    return redirect(url_for("home"))

@app.route("/view/<int:idx>", methods=["GET"])
def view_doc(idx):
    if idx < 0 or idx >= len(engine.doc_paths):
        return "Document not found", 404
    path = engine.doc_paths[idx]
    try:
        return send_file(path, as_attachment=False)
    except Exception:
        return f"Cannot send file: {path}", 500

@app.route("/download/<int:idx>", methods=["GET"])
def download_doc(idx):
    if idx < 0 or idx >= len(engine.doc_paths):
        return "Document not found", 404
    return send_file(engine.doc_paths[idx], as_attachment=True)

@app.route("/export", methods=["POST"])
def export_pdf():
    q = request.form.get("query", "").strip()
    method = request.form.get("method", "tfidf")
    single = request.form.get("single", None)
    if single is not None:
        # export only a single result as PDF
        idx = int(single)
        results = engine.search(q, method=method, top_k=50)  # get up to 50 and filter
        # pick that one
        results = [r for r in results if r['index'] == idx]
    else:
        results = engine.search(q, method=method, top_k=20)

    buf = create_pdf_bytes(q, method, results)
    return send_file(buf, download_name="search_report.pdf", as_attachment=True, mimetype="application/pdf")

@app.route("/sample", methods=["GET"])
def sample_uploaded_file():
    p = Path(UPLOADED_SAMPLE_PATH)
    if p.exists():
        try:
            return send_file(str(p), as_attachment=False)
        except Exception as e:
            return f"Cannot open sample file: {e}", 500
    else:
        return f"Sample uploaded file not found at {UPLOADED_SAMPLE_PATH}.", 404

@app.route("/upload", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        f = request.files.get("file")
        if not f:
            return "No file uploaded", 400
        filename = secure_filename(f.filename)
        if not filename.lower().endswith(ALLOWED_EXT):
            return "Only .txt, .pdf, .docx allowed", 400
        save_path = os.path.join(DOCS_FOLDER, filename)
        f.save(save_path)
        engine.refresh()
        return redirect(url_for("home"))
    return """
    <h3>Upload a file</h3>
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="file"/>
      <input type="submit" value="Upload"/>
    </form>
    """

# ----------------------------
# Run server
# ----------------------------
if __name__ == "__main__":
    print("Loading documents from:", os.path.abspath(DOCS_FOLDER))
    print("Uploaded sample path (dev):", UPLOADED_SAMPLE_PATH)
    print("Starting Flask app on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
