import io
import os
import time
from urllib.parse import unquote_plus

from flask import Blueprint, request, render_template_string, render_template, send_file, redirect, url_for, jsonify
from werkzeug.utils import secure_filename

from app.parsers import ALLOWED_EXT, preprocess, normalize_for_index
from app.ir_engine import IREngine
from app.pdf_exporter import highlight_pdf_bytes, create_search_report_pdf

main_bp = Blueprint("main", __name__)
engine = IREngine()

@main_bp.route("/", methods=["GET", "POST"])
def home():
    results = None
    query = ""
    method = "tfidf"
    folder_status = ""
    if request.method == "POST":
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
        
        if request.form.get("upload") == "1":
            f = request.files.get("file")
            if f:
                fn = secure_filename(f.filename)
                if fn and fn.lower().endswith(ALLOWED_EXT):
                    path = os.path.join(engine.current_folder, fn)
                    f.save(path)
                    engine.refresh()
        
        query = request.form.get("query", "").strip()
        method = request.form.get("method", "tfidf")
        if query:
            results = engine.search(query, method=method, top_k=20)
    
    return render_template(
        "index.html", 
        results=results, 
        n_docs=len(engine.doc_names), 
        query=query, 
        method=method,
        current_folder=engine.current_folder,
        folder_status=folder_status
    )

@main_bp.route("/refresh")
def refresh():
    engine.refresh()
    return redirect(url_for("main.home"))

@main_bp.route("/download/<int:idx>")
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

@main_bp.route("/keywords/<int:idx>")
def keywords(idx):
    if idx < 0 or idx >= len(engine.doc_names):
        return jsonify({"error": "invalid index"}), 404
    try:
        kws = engine.top_keywords(idx, top_n=12)
        return jsonify(kws)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main_bp.route("/highlight/<int:idx>/<query>/<method>")
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

@main_bp.route("/export", methods=["POST"])
def export_report_route():
    q = request.form.get("query", "").strip()
    method = request.form.get("method", "tfidf")
    single = request.form.get("single", None)
    if not q:
        return redirect(url_for("main.home"))
    if single is not None and single != "":
        try:
            idx = int(single)
        except Exception:
            return "<h3>Invalid single index</h3><a href='/'>Back</a>"
        results = engine.search(q, method=method, top_k=50)
        results = [r for r in results if r["index"] == idx]
    else:
        results = engine.search(q, method=method, top_k=50)
    pdf_buf = create_search_report_pdf(q, method, results, total_docs=len(engine.doc_names))
    fname = f"docvista_report_{int(time.time())}.pdf"
    return send_file(pdf_buf, as_attachment=True, download_name=fname, mimetype="application/pdf")

@main_bp.route("/bm25")
def bm25_info():
    return render_template("bm25.html")
