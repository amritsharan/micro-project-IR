import os
import re
import string
import docx

try:
    import pypdf
except ImportError:
    import PyPDF2 as pypdf

import fitz  # PyMuPDF

DOCS_FOLDER = "documents"
ALLOWED_EXT = (".txt", ".pdf", ".docx")

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

def extract_text_from_pdf(path):
    out = ""
    try:
        with open(path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for p in reader.pages:
                try:
                    txt = p.extract_text()
                except Exception:
                    txt = None
                if txt:
                    out += txt + " "
    except Exception:
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

def filter_stopwords(tokens):
    """Remove stopwords from token list"""
    return [t for t in tokens if t and t not in ENGLISH_STOPWORDS]

def load_documents(folder=DOCS_FOLDER, recursive=False):
    """Load documents from a folder, optionally recursively"""
    docs_raw, names, paths = [], [], []
    os.makedirs(folder, exist_ok=True)
    
    if recursive:
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
                    rel_path = os.path.relpath(fp, folder)
                    names.append(f"{rel_path} ({os.path.getsize(fp)} bytes)")
                    paths.append(fp)
    else:
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
    
    esc = re.escape(phrase)
    snippet = re.sub(f"(?i)({esc})", r"<mark>\1</mark>", snippet)
    return snippet
