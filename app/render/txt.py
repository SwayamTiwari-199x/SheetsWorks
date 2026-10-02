"""TXT renderer: writes Doc.plain_text() verbatim."""

from __future__ import annotations

from .doc import Doc


def render_txt(doc: Doc) -> bytes:
    return doc.plain_text().encode("utf-8")
