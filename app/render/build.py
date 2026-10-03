"""Turn a Profile into the canonical Doc, applying rules.json.

Section order, heading wording and page limits all come from rules.json via
app.rules; nothing here is invented from model memory.
"""

from __future__ import annotations

from datetime import date

from .. import rules
from ..models import Profile, Version
from .doc import Doc, Entry, Section

MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def fmt_date(value: str | None) -> str:
    """'2022-07' -> 'Jul 2022'. Never an apostrophe year: RULES.md section 2."""
    if not value:
        return ""
    if value == "Present":
        return "Present"
    parts = value.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        idx = int(parts[1]) - 1
        if 0 <= idx < 12:
            return f"{MONTHS[idx]} {parts[0]}"
    return value


def fmt_range(start: str | None, end: str | None) -> str:
    a, b = fmt_date(start), fmt_date(end)
    if a and b:
        return f"{a} - {b}"
    return a or b


def detect_level(profile: Profile) -> str:
    """student vs experienced, from real work months rather than a flag.

    Internships and freelance do not count: RULES.md section 6 treats them as
    the fresher's experience, so they must not tip the layout into the
    experienced two-page template.
    """
    months = 0
    now = date.today()
    for exp in profile.experience:
        if exp.type != "job":
            continue
        start = exp.start[:4]
        end = exp.end if exp.end and exp.end != "Present" else str(now.year)
        try:
            months += max(0, int(end[:4]) - int(start) + 1) * 12
        except ValueError:
            continue
    return "experienced" if months >= 12 else "student"


def _bullets(items) -> list[str]:
    return [b.text for b in items if b.text]


def _contact_lines(profile: Profile) -> list[str]:
    c = profile.contact
    parts = [c.email, c.phone]
    city = ", ".join(p for p in (c.city, c.country) if p)
    if city:
        parts.append(city)
    parts.extend(link.url for link in c.links if link.url)
    line = " | ".join(p for p in parts if p)
    return [line] if line else []


def build_doc(
    profile: Profile,
    *,
    include_personal_details: bool = False,
    template: str | None = None,
) -> Doc:
    """Flatten a Profile into the canonical document.

    The template decides which sections appear and in what order; both come from
    rules.json, never from this file. Personal details are opt-in and off by
    default (SPEC section 4), and are read as text only -- no path is opened.
    """
    level = detect_level(profile)
    spec = rules.template(template)
    order = rules.template_order(template, level)

    # group work vs internships so both can occupy their own slot
    jobs = [e for e in profile.experience if e.type == "job"]
    internships = [e for e in profile.experience if e.type != "job"]

    by_key: dict[str, Section] = {}

    by_key["summary"] = Section(
        "summary",
        rules.heading("summary"),
        [Entry(header="", meta=profile.summary)] if profile.summary else [],
    )

    # One free-text line, rendered as "Interests: ..." — only in templates that
    # ask for it (see rules.json resume_templates).
    by_key["interests"] = Section(
        "interests",
        rules.heading("interests"),
        [Entry(header="", meta=profile.interests)] if profile.interests else [],
    )

    def work_section(key: str, items) -> Section:
        entries = []
        for e in items:
            entries.append(
                Entry(
                    header=f"{e.role}, {e.org}",
                    meta=fmt_range(e.start, e.end),
                    bullets=_bullets(e.bullets),
                )
            )
        return Section(key, rules.heading(key), entries)

    # For a student, internships and any jobs share the single Experience slot.
    if level == "student":
        by_key["internships_experience"] = work_section(
            "internships_experience", [*internships, *jobs]
        )
    else:
        by_key["work_experience"] = work_section("work_experience", jobs)
        if internships:
            by_key["internships_experience"] = work_section(
                "internships_experience", internships
            )

    by_key["projects"] = Section(
        "projects",
        rules.heading("projects"),
        [
            Entry(
                header=f"{p.name}" + (f", {p.role}" if p.role else ""),
                meta=" | ".join(x for x in [", ".join(p.tech), fmt_range(p.start, p.end)] if x),
                bullets=_bullets(p.bullets),
            )
            for p in profile.projects
            if p.name
        ],
    )

    by_key["education"] = Section(
        "education",
        rules.heading("education"),
        [
            Entry(
                header=f"{e.institution}" + (f", {e.degree}" if e.degree else ""),
                meta=" | ".join(
                    x
                    for x in [
                        fmt_range(e.start, e.end),
                        (f"{e.grade.value}/{e.grade.scale}" if e.grade else ""),
                        (f"Coursework: {', '.join(e.coursework)}" if e.coursework else ""),
                    ]
                    if x
                ),
            )
            for e in profile.education
            if e.institution
        ],
    )

    by_key["skills"] = Section(
        "skills",
        rules.heading("skills"),
        [
            Entry(header=g.name, meta=", ".join(g.items))
            for g in profile.skills
            if g.name and g.items
        ],
    )

    def simple(items) -> list[Entry]:
        return [
            Entry(
                header=i.name,
                meta=" | ".join(x for x in [i.issuer, fmt_date(i.date)] if x),
            )
            for i in items
            if i.name
        ]

    by_key["certifications"] = Section(
        "certifications", rules.heading("certifications"), simple(profile.certifications)
    )
    by_key["achievements_awards"] = Section(
        "achievements_awards",
        rules.heading("achievements_awards"),
        simple(profile.achievements) + simple(profile.extracurriculars),
    )
    by_key["publications"] = Section(
        "publications", rules.heading("publications"), simple(profile.publications)
    )

    # A template may deliberately exclude a section (sheets drops the summary).
    # That is the template speaking, not data loss, so it is applied before the
    # no-data-loss fallback below.
    if not spec.get("include_summary", True):
        by_key.pop("summary", None)
    if not spec.get("include_interests", False):
        by_key.pop("interests", None)

    sections = [by_key[key] for key in order if key in by_key]

    # Honouring section_order must not mean silently dropping the user's data:
    # anything populated that the order did not place is appended, per
    # rules.json section_order.fallback_append.
    placed = {key for key in order if key in by_key}
    sections.extend(
        by_key[key]
        for key in rules.fallback_append()
        if key not in placed and by_key[key].entries
    )

    # Interests is explicitly last when the template asks for it.
    if spec.get("include_interests"):
        sections = [s for s in sections if s.key != "interests"]
        if by_key["interests"].entries:
            sections.append(by_key["interests"])

    contact = _contact_lines(profile)
    if include_personal_details:
        extra = _personal_lines(profile)
        if extra:
            contact = contact + extra

    return Doc(
        name=profile.contact.name,
        contact_lines=contact,
        sections=sections,
        level=level,
    )


def _personal_lines(profile: Profile) -> list[str]:
    """Text only. photo_path is deliberately never opened (traversal risk)."""
    p = profile.personal_details
    bits = []
    if p.date_of_birth:
        bits.append(f"DOB: {p.date_of_birth}")
    for label, value in (
        ("Gender", p.gender),
        ("Marital Status", p.marital_status),
        ("Father's Name", p.fathers_name),
    ):
        if value:
            bits.append(f"{label}: {value}")
    return [" | ".join(bits)] if bits else []


def build_doc_from_version(version: Version) -> Doc:
    return build_doc(
        version.profile_snapshot,
        include_personal_details=version.include_personal_details,
        template=version.template,
    )
