"""DOCX renderer.

Walks Doc.blocks() and emits one paragraph per block, so the text content is
identical to the TXT render by construction. Only formatting differs: headings
and entry headers are bold.
"""

from __future__ import annotations

import io

from docx import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from .. import rules
from .doc import BOLD_KINDS, BULLET, BULLET_MARK, Doc


def render_docx(doc: Doc) -> bytes:
    d = DocxDocument()

    normal = d.styles["Normal"]
    normal.font.name = rules.font_family().split(",")[0]
    normal.font.size = Pt(rules.body_size_pt())

    for kind, text in doc.blocks():
        para = d.add_paragraph()
        if kind == BULLET:
            # A literal ASCII hyphen, not Word's automatic list glyph: the glyph
            # extracts as U+FFFD in converted PDFs (RULES.md section 2).
            para.paragraph_format.left_indent = Pt(18)
            para.add_run(f"{BULLET_MARK} {text}")
        elif kind in BOLD_KINDS:
            para.add_run(text).bold = True
        else:
            para.add_run(text)

        if kind in BOLD_KINDS:
            para.paragraph_format.space_before = Pt(6)
            para.paragraph_format.space_after = Pt(2)
        elif kind == BULLET:
            para.paragraph_format.space_after = Pt(2)

    # ATS-safe: left aligned, single column. python-docx defaults are already
    # single column, so nothing to flatten here.
    for para in d.paragraphs:
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT

    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
