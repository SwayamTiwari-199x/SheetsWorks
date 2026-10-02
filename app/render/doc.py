"""The canonical rendered document.

Everything the three renderers need is flattened here into one ordered list of
blocks. PDF, DOCX and TXT all consume `Doc.blocks()`, which is what makes the
"DOCX contains the same text as the TXT" guarantee true by construction rather
than by three renderers happening to agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Block kinds, in the order they can appear.
NAME = "name"
CONTACT = "contact"
HEADING = "heading"
ENTRY_HEADER = "entry_header"
ENTRY_META = "entry_meta"
BULLET = "bullet"
PLAIN = "plain"

BOLD_KINDS = {NAME, HEADING, ENTRY_HEADER}

# Monospace-safe ASCII hyphen. A CSS list marker renders a glyph that extracts as
# U+FFFD in the PDF, which is exactly the "decorative bullet glyphs can garble"
# pitfall in RULES.md section 2.
BULLET_MARK = "-"


@dataclass
class Entry:
    header: str = ""
    meta: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class Section:
    key: str
    heading: str
    entries: list[Entry] = field(default_factory=list)


@dataclass
class Doc:
    name: str
    contact_lines: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    level: str = "experienced"

    def blocks(self) -> list[tuple[str, str]]:
        """Flatten to an ordered (kind, text) list. The renderers' only input."""
        out: list[tuple[str, str]] = []
        if self.name:
            out.append((NAME, self.name))
        for line in self.contact_lines:
            if line:
                out.append((CONTACT, line))
        for section in self.sections:
            if not section.entries:
                continue
            out.append((HEADING, section.heading))
            for entry in section.entries:
                if entry.header:
                    out.append((ENTRY_HEADER, entry.header))
                if entry.meta:
                    out.append((ENTRY_META, entry.meta))
                for bullet in entry.bullets:
                    if bullet:
                        out.append((BULLET, bullet))
        return out

    def plain_text(self) -> str:
        """The canonical linear text. TXT writes this; DOCX reproduces it."""
        lines = []
        for kind, text in self.blocks():
            lines.append(f"{BULLET_MARK} {text}" if kind == BULLET else text)
        return "\n".join(lines) + "\n"
