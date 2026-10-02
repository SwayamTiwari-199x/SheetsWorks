"""PDF renderer: WeasyPrint + one ATS-safe Jinja2 template.

Why WeasyPrint and not Tectonic: measured on a realistic fresher resume,
Tectonic + Calibri dropped *every word space* during text extraction
('BITS Pilani' -> 'BITSPilani'). A PDF whose text an ATS cannot parse defeats
the purpose of the tool. WeasyPrint extracted 19/19 content canaries cleanly
and renders in ~260ms versus ~4.7s.

Why not PDF built by hand: layout is entirely CSS, so single-column, margins
and font come straight from rules.json.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
import weasyprint

from .. import rules
from .doc import BOLD_KINDS, BULLET, BULLET_MARK, Doc

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"

# Progressive density, tried in order until the page budget is met.
#
# Only whitespace is compressed. The body font is never scaled below
# rules.json ats.fonts.body_size_pt minimum (10.5pt) and margins never below
# ats.margins_inches.min (0.5in), because those two bounds are researched
# ATS-safety limits, not taste. If the tightest density still overflows, the
# caller is told so it can trim content -- that is Stage 6's job, not ours.
DENSITIES = [
    {"name": "normal", "margin": 1.0, "line_height": 1.22},
    {"name": "compact", "margin": 0.75, "line_height": 1.14},
    {"name": "tight", "margin": 0.5, "line_height": 1.08},
]


@lru_cache
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _html(doc: Doc, density: dict) -> str:
    return _env().get_template("resume.html").render(
        blocks=doc.blocks(),
        bold_kinds=BOLD_KINDS,
        bullet_kind=BULLET,
        bullet_mark=BULLET_MARK,
        font_family=rules.font_family(),
        body_size_pt=rules.body_size_pt(),
        margin_inches=density["margin"],
        line_height=density["line_height"],
        heading_gap=density["margin"] * 0.7,
    )


def render_pdf(doc: Doc, max_pages: int | None = None) -> bytes:
    """Render to PDF bytes, compressing whitespace only if needed to fit."""
    pdf, _, _ = _render(doc, max_pages)
    return pdf


def render_pdf_with_page_count(doc: Doc, max_pages: int | None = None) -> tuple[bytes, int]:
    """Same as render_pdf but also returns the page count."""
    pdf, pages, _ = _render(doc, max_pages)
    return pdf, pages


def render_pdf_report(doc: Doc, max_pages: int | None = None) -> tuple[bytes, int, str]:
    """Returns (pdf_bytes, page_count, density_name).

    ``density_name`` tells you how hard the layout had to squeeze; if it had to
    use "tight" and still overflowed, content must be trimmed instead.
    """
    return _render(doc, max_pages)


def _render(doc: Doc, max_pages: int | None) -> tuple[bytes, int, str]:
    if max_pages is None:
        max_pages = rules.page_limit(doc.level)

    last: tuple[bytes, int, str] | None = None
    for density in DENSITIES:
        document = weasyprint.HTML(string=_html(doc, density)).render()
        buf = io.BytesIO()
        document.write_pdf(buf)
        last = (buf.getvalue(), len(document.pages), density["name"])
        if last[1] <= max_pages:
            return last

    assert last is not None
    return last
