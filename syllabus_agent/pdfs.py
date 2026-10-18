"""Text per page from an uploaded PDF. No OCR: a scanned PDF is reported and skipped."""

import hashlib
import io

MIN_CHARS_PER_PAGE = 20


class NoText(ValueError):
    pass


def page_texts(data):
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except Exception:
        from pypdf import PdfReader
        return [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages]


def read_pdf(name, data):
    """Return {"name", "sha256", "pages"}; pages are 1-indexed by position + 1."""
    pages = page_texts(data)
    if sum(len(p.strip()) for p in pages) < MIN_CHARS_PER_PAGE * max(len(pages), 1):
        raise NoText(f"{name} has no extractable text (probably scanned). Skipped: OCR isn't supported.")
    return {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "pages": pages}


def marked(syllabus, only=None):
    """The text a worker sees, with page markers it can cite. Each page is closed too: many PDFs print
    their page number at the foot of a page, right before the next marker, and models then misattribute."""
    return "\n\n".join(f"=== Page {n} ===\n{text}\n=== End of page {n} ==="
                       for n, text in enumerate(syllabus["pages"], 1) if only is None or n in only)
