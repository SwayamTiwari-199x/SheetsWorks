"""Renderers: profile/version JSON -> ATS-safe PDF, DOCX, TXT.

All three read the same canonical Doc, so their text content cannot drift apart.
"""

from .build import build_doc, build_doc_from_version, detect_level, fmt_date, fmt_range
from .doc import BULLET_MARK, Doc, Entry, Section
from .docx import render_docx
from .pdf import DENSITIES, render_pdf, render_pdf_report, render_pdf_with_page_count
from .txt import render_txt

__all__ = [
    "BULLET_MARK",
    "DENSITIES",
    "Doc",
    "Entry",
    "Section",
    "build_doc",
    "build_doc_from_version",
    "detect_level",
    "fmt_date",
    "fmt_range",
    "render_docx",
    "render_pdf",
    "render_pdf_report",
    "render_pdf_with_page_count",
    "render_txt",
    "RENDERERS",
]

RENDERERS = {"pdf": render_pdf, "docx": render_docx, "txt": render_txt}

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain; charset=utf-8",
}
