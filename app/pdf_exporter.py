import io
import os
import time
import unicodedata
import fitz  # PyMuPDF
from fpdf import FPDF

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

def normalize_text_for_pdf(text):
    if text is None:
        return ""
    replacements = {
        '\u2013': '-', '\u2014': '-', '\u2015': '-',
        '\u2212': '-', '\u2022': '*', '\u00A0': ' ',
        '\u200b': '', '\u200c': '', '\u200d': '', '\u200e': '', '\u200f': '',
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in '\n\t')
    text = "".join(ch if ord(ch) < 128 or ord(ch) >= 160 else '' for ch in text)
    return str(text).strip()

def clean_line_for_pdf(line):
    if line is None:
        return ""
    line = str(line).replace("\t", " ").replace("\r", " ")
    problematic_chars = {'\u200b', '\u200c', '\u200d', '\u200e', '\u200f', '\ufeff'}
    for char in problematic_chars:
        line = line.replace(char, '')
    return ''.join(ch for ch in line if (32 <= ord(ch) <= 126) or (160 <= ord(ch) <= 255) or ch in '\n')

def create_search_report_pdf(query, method, results, total_docs=0):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    font_candidates = ["fonts/DejaVuSans.ttf", "fonts/ttf/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"]
    base_font = "helvetica"
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

    if custom_font_loaded:
        pdf.set_font(base_font, size=18)
    else:
        pdf.set_font(base_font, "B", size=18)
    pdf.cell(0, 10, "DocVista - Search Report", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font(base_font, size=10)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(0, 6, f"Query: {clean_line_for_pdf(query)}", ln=True, fill=True)
    pdf.cell(0, 6, f"Method: {method.upper()}", ln=True, fill=True)
    pdf.cell(0, 6, f"Results: {len(results)} documents", ln=True, fill=True)
    pdf.cell(0, 6, f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}", ln=True, fill=True)
    pdf.ln(5)

    if custom_font_loaded:
        pdf.set_font(base_font, size=11)
    else:
        pdf.set_font(base_font, "B", size=11)
    pdf.set_fill_color(40, 40, 40)
    pdf.set_text_color(255, 255, 255)
    
    col_no = 12
    col_name = 130
    col_score = 38
    
    pdf.cell(col_no, 8, "#", border=1, fill=True, align="C")
    pdf.cell(col_name, 8, "Document Name", border=1, fill=True, align="L")
    pdf.cell(col_score, 8, "Score", border=1, fill=True, align="C")
    pdf.ln(8)

    pdf.set_font(base_font, size=10)
    pdf.set_text_color(0, 0, 0)
    
    for i, r in enumerate(results, start=1):
        fill = (i % 2 == 0)
        pdf.set_fill_color(240, 240, 240) if fill else pdf.set_fill_color(255, 255, 255)
        
        doc_name = clean_line_for_pdf(r['name'][:50])
        score_str = f"{r['score']:.4f}"
        
        pdf.cell(col_no, 8, str(i), border=1, fill=fill, align="C")
        pdf.cell(col_name, 8, doc_name, border=1, fill=fill, align="L")
        pdf.cell(col_score, 8, score_str, border=1, fill=fill, align="C")
        pdf.ln(8)

    pdf.ln(5)
    pdf.set_font(base_font, size=9) if custom_font_loaded else pdf.set_font(base_font, "I", size=9)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4, f"Ranking Method: {method.upper()} | Total Documents Indexed: {total_docs} | Page {pdf.page_no()}")

    pdf_bytes = pdf.output(dest='S')
    if isinstance(pdf_bytes, str):
        pdf_bytes = pdf_bytes.encode('latin-1', 'replace')
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    return buf
