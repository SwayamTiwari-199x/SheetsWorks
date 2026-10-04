"""Load conventions from rules.json.

CLAUDE.md non-negotiable: ATS/layout/writing conventions come from RULES.md
(researched in Stage 0), not from the model's memory. This module is the only
place the app reads those rules, so there is exactly one source of truth.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "rules.json"


class RulesError(RuntimeError):
    """rules.json missing or malformed."""


@lru_cache
def load_rules() -> dict:
    if not RULES_PATH.exists():
        raise RulesError(f"rules.json not found at {RULES_PATH}")
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RulesError(f"rules.json is not valid JSON: {exc}") from exc


# --- headings --------------------------------------------------------------
# Display headings must come from rules.json `safe_headings.acceptable`, so an
# ATS-recognised label is never invented here.


def _acceptable() -> set[str]:
    return {h.lower() for h in load_rules()["safe_headings"]["acceptable"]}


def heading(section: str) -> str:
    """Map an internal section key to an ATS-safe display heading.

    Raises rather than inventing a heading if rules.json does not sanction one.
    """
    table = {
        "summary": "Summary",
        "work_experience": "Work Experience",
        "projects": "Projects",
        "skills": "Skills",
        "education": "Education",
        "certifications": "Certifications",
        "achievements_awards": "Achievements",
        "publications": "Publications",
        # Freshers put internships under Experience: "Internships" is not on the
        # safe list and ATS parsers expect "Experience".
        "internships_experience": "Experience",
        "interests": "Interests",
    }
    try:
        label = table[section]
    except KeyError:
        raise RulesError(f"no heading mapped for section {section!r}") from None
    if label.lower() not in _acceptable():
        raise RulesError(
            f"heading {label!r} for {section!r} is not in rules.json safe_headings"
        )
    return label


def section_order(level: str) -> list[str]:
    """Ordered section keys for a candidate level ('student' or 'experienced')."""
    order = load_rules()["section_order"]
    key = "student_fresher" if level == "student" else "experienced"
    return list(order[key])


def fallback_append() -> list[str]:
    """Sections that are appended if populated but absent from section_order.

    Belt and braces against silent data loss. RULES.md section 3 does not place
    every possible section for every level, and a renderer that iterated
    section_order exactly once dropped whatever was missing.
    """
    return list(load_rules()["section_order"].get("fallback_append", []))


def tips() -> list[dict]:
    """The research-backed advice shown in the front page NEWS panel.

    Served from rules.json rather than hardcoded in the markup so that what a
    user reads on screen is the cited research in RULES.md, not a paraphrase
    invented by the UI.
    """
    return list(load_rules().get("tips", []))


# --- resume templates -----------------------------------------------------
# A template decides which sections appear and in what order. Both are defined in
# rules.json so the renderer never hardcodes a convention (CLAUDE.md rule 4), and
# so the two genuinely conflicting sources stay visible side by side.


def template_names() -> list[str]:
    return [k for k in load_rules()["resume_templates"] if k not in ("default", "why_not_merge")]


def default_template() -> str:
    return load_rules()["resume_templates"]["default"]


def template(name: str | None = None) -> dict:
    """The template definition, falling back to the default for unknown names.

    Falling back matters: Version rows written before templates existed carry
    "ats", which is not a template, and those versions must still export.
    """
    templates = load_rules()["resume_templates"]
    chosen = name or templates["default"]
    if chosen not in templates:
        chosen = templates["default"]
    return templates[chosen]


def template_order(name: str | None, level: str) -> list[str]:
    spec = template(name)
    key = "student_fresher" if level == "student" else "experienced"
    orders = spec["orders"]
    if isinstance(orders[key], list):
        return list(orders[key])
    # Orders that alias the researched default. section_order() takes the LEVEL,
    # not the key -- passing the key here silently returned the experienced
    # layout for students, which put Education after Skills and dropped their
    # internships entirely.
    return section_order("student" if key == "student_fresher" else "experienced")


# --- layout / limits -------------------------------------------------------


def page_limit(level: str) -> int:
    """Max pages allowed for this level (rules.json page_limits)."""
    limits = load_rules()["page_limits"]
    return int(limits[level]["max"])


def font_family() -> str:
    """First ATS-safe font from rules.json, with generic fallbacks."""
    safe = load_rules()["ats"]["fonts"]["safe"]
    return f"{safe[0]}, {safe[1]}, sans-serif"


def body_size_pt() -> float:
    lo, hi = load_rules()["ats"]["fonts"]["body_size_pt"]
    return float(lo)


def margins_inches() -> float:
    return float(load_rules()["ats"]["margins_inches"]["recommended"])


def safe_fonts() -> set[str]:
    return {f.lower() for f in load_rules()["ats"]["fonts"]["safe"]}


def layout_rules() -> list[str]:
    return list(load_rules()["ats"]["layout_rules"])


def banned_phrases() -> list[str]:
    return list(load_rules()["banned_phrases"])


def market_snapshot_is_stale(today: str) -> bool:
    """True when the job-market block has reached its refresh date.

    Stale *on* ``stale_after`` (>=), not after it: that date is the day the
    data expires. Machine-checkable on purpose, because prose saying "refresh
    soon" cannot be acted on by code or asserted by a test.
    """
    snap = load_rules()["market_snapshot"]
    return today >= snap["stale_after"]
