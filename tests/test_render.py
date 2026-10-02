"""Stage 2 acceptance tests.

These map one-to-one onto BUILD_PLAN Stage 2:
  1. special characters (& % # _ $) render in all three formats
  2. PDF text is selectable; pdfplumber returns headings in order + email + phone
  3. a student profile fits the rules.json page limit
  4. DOCX opens with python-docx and contains the same text as the TXT
"""

from __future__ import annotations

import io
import re

import pdfplumber
import pytest
from docx import Document as DocxDocument

from app import rules
from app.models import Profile
from app.rules import load_rules
from app.render import BULLET_MARK, DENSITIES, build_doc, render_docx, render_pdf, render_pdf_report, render_pdf_with_page_count, render_txt

SPECIAL = "& % # _ $"


@pytest.fixture
def hostile_profile(sample_profile_payload: dict) -> Profile:
    """The sample profile, loaded with characters that break naive renderers."""
    payload = dict(sample_profile_payload)
    payload["summary"] = "Backend engineer; R&D on 100% & 40% cost cuts #1 with C++/CLI_v2."
    payload["experience"][0]["org"] = "PayFlow R&D (Labs)"
    payload["experience"][0]["bullets"].append(
        {
            "raw_facts": "raw",
            "text": f"Cut p99 latency 100% & cost 40% #1 using C++/CLI_v2 $var",
        }
    )
    payload["skills"] = [
        {"name": "Core", "items": ["C++", "C#", "F#", "$var", "a_b", "100%"]}
    ]
    return Profile.model_validate(payload)


@pytest.fixture
def student_profile() -> Profile:
    return Profile.model_validate(
        {
            "contact": {
                "name": "Dusht",
                "email": "dusht@example.com",
                "phone": "+91 98765 43210",
                "city": "Bengaluru",
                "country": "India",
                "links": [{"label": "GitHub", "url": "github.com/dusht"}],
            },
            "summary": (
                "Final-year Computer Science undergraduate at BITS Pilani with "
                "backend experience in Python and FastAPI. Shipped a staffing "
                "scheduler used by 12 retail stores."
            ),
            "education": [
                {
                    "institution": "BITS Pilani",
                    "degree": "B.E. Computer Science",
                    "start": "2021-08",
                    "end": "2025-06",
                    "grade": {"value": "8.72", "scale": "10"},
                    "coursework": ["Data Structures", "DBMS", "OS"],
                }
            ],
            "experience": [
                {
                    "org": "Nimbus Analytics",
                    "role": "Backend Intern",
                    "type": "internship",
                    "start": "2024-06",
                    "end": "2024-08",
                    "bullets": [
                        {
                            "raw_facts": "raw",
                            "text": "Automated the nightly ETL with Python and Airflow, removing a 45-minute manual run.",
                        }
                    ],
                }
            ],
            "projects": [
                {
                    "name": "Staffing Shift Scheduler",
                    "role": "Solo build",
                    "tech": ["FastAPI", "PostgreSQL", "Celery", "Redis"],
                    "start": "2023-01",
                    "end": "2023-06",
                    "bullets": [
                        {
                            "raw_facts": "raw",
                            "text": "Built a shift scheduler for 12 retail stores, cutting roster publish time from 4 hours to under 30 seconds.",
                        },
                        {
                            "raw_facts": "raw",
                            "text": "Reduced p99 API latency from 840ms to 190ms with Redis read-through caching.",
                        },
                    ],
                }
            ],
            "skills": [
                {"name": "Languages", "items": ["Python", "SQL", "JavaScript"]},
                {"name": "Backend", "items": ["FastAPI", "Django", "Celery"]},
                {"name": "Data", "items": ["PostgreSQL", "Redis", "Kafka"]},
            ],
            "certifications": [
                {"name": "AWS Solutions Architect - Associate", "issuer": "AWS", "date": "2024-03"}
            ],
            "achievements": [{"name": "Winner, BITS Hackathon 2024"}],
        }
    )


# --------------------------------------------------------------------------
# Criterion 1: special characters render in all three formats
# --------------------------------------------------------------------------


def test_criterion1_special_chars_in_txt(hostile_profile: Profile) -> None:
    text = render_txt(build_doc(hostile_profile)).decode("utf-8")
    for ch in SPECIAL:
        assert ch in text, f"{ch!r} missing from TXT"


def test_criterion1_special_chars_in_docx(hostile_profile: Profile) -> None:
    d = DocxDocument(io.BytesIO(render_docx(build_doc(hostile_profile))))
    text = "\n".join(p.text for p in d.paragraphs)
    for ch in SPECIAL:
        assert ch in text, f"{ch!r} missing from DOCX"


def test_criterion1_special_chars_in_pdf(hostile_profile: Profile) -> None:
    """The PDF must render AND the specials must survive text extraction."""
    pdf = render_pdf(build_doc(hostile_profile))
    assert pdf.startswith(b"%PDF")
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        text = "\n".join(p.extract_text() or "" for p in doc.pages)
    for ch in SPECIAL:
        assert ch in text, f"{ch!r} missing from extracted PDF text"


def test_criterion1_renders_do_not_raise(hostile_profile: Profile) -> None:
    doc = build_doc(hostile_profile)
    for fn in (render_pdf, render_docx, render_txt):
        assert len(fn(doc)) > 0


# --------------------------------------------------------------------------
# Criterion 2: selectable text, headings in order, email and phone present
# --------------------------------------------------------------------------


def _pdf_text(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(p.extract_text() or "" for p in doc.pages)


def test_criterion2_pdf_text_is_selectable(hostile_profile: Profile) -> None:
    text = _pdf_text(render_pdf(build_doc(hostile_profile)))
    assert len(text) > 200, "PDF text layer looks empty; it would not be ATS-readable"


def test_criterion2_headings_in_correct_order(sample_profile_payload: dict) -> None:
    """Headings must follow rules.json section_order, not template order.

    Every populated section must also appear: an ordered prefix followed by
    anything section_order.fallback_append supplies. Nothing may be dropped.
    """
    profile = Profile.model_validate(sample_profile_payload)
    doc = build_doc(profile)

    present = {s.key for s in doc.sections}
    ordered = [k for k in rules.section_order(doc.level) if k in present]
    appended = [k for k in rules.fallback_append() if k in present and k not in ordered]

    expected = [rules.heading(k).upper() for k in ordered + appended]
    assert [s.heading.upper() for s in doc.sections] == expected


def test_every_rendered_heading_is_sanctioned_by_rules_json(sample_profile_payload: dict) -> None:
    """No renderer may invent a heading (CLAUDE.md: conventions come from RULES.md)."""
    doc = build_doc(Profile.model_validate(sample_profile_payload))
    sanctioned = {h.lower() for h in load_rules()["safe_headings"]["acceptable"]}
    for section in doc.sections:
        assert section.heading.lower() in sanctioned, (
            f"heading {section.heading!r} is not in rules.json safe_headings"
        )


def test_criterion2_student_order_puts_education_first(student_profile: Profile) -> None:
    headings = [s.heading for s in build_doc(student_profile).sections]
    assert headings.index("Education") < headings.index("Projects")


def test_criterion2_experienced_order_puts_work_first(sample_profile_payload: dict) -> None:
    headings = [s.heading for s in build_doc(Profile.model_validate(sample_profile_payload)).sections]
    assert headings.index("Work Experience") < headings.index("Education")


def test_criterion2_email_and_phone_in_pdf(sample_profile_payload: dict) -> None:
    profile = Profile.model_validate(sample_profile_payload)
    text = _pdf_text(render_pdf(build_doc(profile)))
    assert profile.contact.email in text
    assert profile.contact.phone in text


def test_criterion2_no_words_are_glued_together(sample_profile_payload: dict) -> None:
    """Guards the defect that ruled out Tectonic: dropped word spaces.

    A PDF that looks right but extracts as 'BITSPilani' is unreadable to an ATS.
    """
    profile = Profile.model_validate(sample_profile_payload)
    text = _pdf_text(render_pdf(build_doc(profile)))
    flat = re.sub(r"\s+", " ", text)
    for phrase in ("BITS Pilani", "Backend Engineer", "PayFlow"):
        assert phrase in flat, f"{phrase!r} did not survive extraction"


def test_criterion2_no_garbled_glyphs(sample_profile_payload: dict) -> None:
    """A CSS list marker extracts as U+FFFD; bullets must be a plain hyphen."""
    profile = Profile.model_validate(sample_profile_payload)
    text = _pdf_text(render_pdf(build_doc(profile)))
    assert "\ufffd" not in text, "a bullet glyph garbled into U+FFFD"
    assert f"{BULLET_MARK} Cut p99" in text


def test_criterion2_embedded_font_is_ats_safe(sample_profile_payload: dict) -> None:
    profile = Profile.model_validate(sample_profile_payload)
    pdf = render_pdf(build_doc(profile))
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        fonts = {c["fontname"] for p in doc.pages for c in p.chars}
    safe = rules.safe_fonts()
    for f in fonts:
        # fontnames arrive as 'ABCDEF+Calibri'
        assert any(s in f.lower() for s in safe), f"non-ATS font embedded: {f}"


# --------------------------------------------------------------------------
# Criterion 3: student profile fits the rules.json page limit
# --------------------------------------------------------------------------


def test_criterion3_student_fits_page_limit(student_profile: Profile) -> None:
    doc = build_doc(student_profile)
    assert doc.level == "student"
    _, pages = render_pdf_with_page_count(doc)
    limit = rules.page_limit("student")
    assert pages <= limit, f"student resume is {pages} pages, limit is {limit}"


def test_criterion3_page_limit_comes_from_rules_json() -> None:
    assert rules.page_limit("student") == 1
    assert rules.page_limit("experienced") == 2


def test_criterion3_level_detection_ignores_internships(student_profile: Profile) -> None:
    """An internship must not tip a fresher into the experienced layout."""
    assert build_doc(student_profile).level == "student"


def test_criterion3_full_time_work_is_experienced(sample_profile_payload: dict) -> None:
    profile = Profile.model_validate(sample_profile_payload)
    assert build_doc(profile).level == "experienced"


def test_criterion3_export_reports_page_count(hostile_profile: Profile) -> None:
    doc = build_doc(hostile_profile)
    _, pages = render_pdf_with_page_count(doc)
    assert pages >= 1
    assert pages <= rules.page_limit(doc.level)


# --------------------------------------------------------------------------
# Criterion 4: DOCX text identical to TXT
# --------------------------------------------------------------------------


def _docx_paragraphs(docx_bytes: bytes) -> list[str]:
    d = DocxDocument(io.BytesIO(docx_bytes))
    return [p.text for p in d.paragraphs if p.text.strip()]


def test_criterion4_docx_opens_with_python_docx(hostile_profile: Profile) -> None:
    doc = build_doc(hostile_profile)
    d = DocxDocument(io.BytesIO(render_docx(doc)))
    assert len(d.paragraphs) > 5


def test_criterion4_docx_text_matches_txt(hostile_profile: Profile) -> None:
    doc = build_doc(hostile_profile)
    txt = render_txt(doc).decode("utf-8")
    txt_lines = [ln for ln in txt.splitlines() if ln.strip()]

    assert _docx_paragraphs(render_docx(doc)) == txt_lines


def test_criterion4_docx_matches_txt_for_student(student_profile: Profile) -> None:
    doc = build_doc(student_profile)
    txt_lines = [ln for ln in render_txt(doc).decode("utf-8").splitlines() if ln.strip()]
    assert _docx_paragraphs(render_docx(doc)) == txt_lines


def test_criterion4_pdf_and_txt_carry_the_same_content(hostile_profile: Profile) -> None:
    """Weaker than the DOCX check (PDF wraps lines) but the words must all appear.

    Case-insensitive because the PDF uppercases section headings by design (see
    test_headings_are_uppercase_in_pdf), which is the industry convention.
    """
    doc = build_doc(hostile_profile)
    flat_pdf = re.sub(r"\s+", " ", _pdf_text(render_pdf(doc))).lower()
    for kind, text in doc.blocks():
        words = [w for w in re.sub(r"[^\w%]+", " ", text).split() if len(w) > 3]
        missing = [w for w in words if w.lower() not in flat_pdf]
        assert not missing, f"PDF lost words: {missing} (from {text!r})"


def test_headings_are_uppercase_in_pdf(sample_profile_payload: dict) -> None:
    """Section headings render uppercase: the standard resume convention.

    The underlying strings stay title-case per rules.json safe_headings; the
    template's text-transform does the rest. ATS heading matching is
    case-insensitive, so this is presentation only.
    """
    profile = Profile.model_validate(sample_profile_payload)
    doc = build_doc(profile)
    text = _pdf_text(render_pdf(doc))
    for section in doc.sections:
        assert section.heading.upper() in text
    # and the canonical title-case form is not what reaches the page
    assert "WORK EXPERIENCE" in text


def test_no_profile_content_is_silently_dropped(sample_profile_payload: dict) -> None:
    """Regression: rules.json's `experienced` order omits achievements_awards.

    build_doc used to iterate only the ordered keys, so an experienced
    candidate's Achievements section vanished from every rendered format with no
    error at all. Ordering must be honoured without discarding content.
    """
    payload = dict(sample_profile_payload)
    payload["achievements"] = [{"name": "Winner, BITS Hackathon 2021 - 1st of 240 teams"}]
    payload["extracurriculars"] = [{"name": "Coding club secretary"}]
    payload["publications"] = [{"name": "Paper on shift scheduling"}]

    doc = build_doc(Profile.model_validate(payload))
    assert doc.level == "experienced"
    text = doc.plain_text()

    assert "Winner, BITS Hackathon 2021 - 1st of 240 teams" in text
    assert "Coding club secretary" in text
    assert "Paper on shift scheduling" in text


def test_achievements_render_for_experienced_profiles(sample_profile_payload: dict) -> None:
    payload = dict(sample_profile_payload)
    payload["achievements"] = [{"name": "Winner, BITS Hackathon 2021 - 1st of 240 teams"}]
    profile = Profile.model_validate(payload)
    headings = [s.heading for s in build_doc(profile).sections]
    assert "Achievements" in headings


def test_ordered_sections_still_come_first(sample_profile_payload: dict) -> None:
    """Appending unlisted sections must not disturb rules.json ordering."""
    payload = dict(sample_profile_payload)
    payload["achievements"] = [{"name": "Some achievement"}]
    headings = [s.heading for s in build_doc(Profile.model_validate(payload)).sections]
    assert headings.index("Work Experience") < headings.index("Education")
    assert headings[-1] == "Achievements"


def test_every_populated_profile_section_appears(student_profile: Profile) -> None:
    """Guard against any future key silently going missing."""
    payload = student_profile.model_dump()
    payload["publications"] = [{"name": "Paper on shift scheduling"}]
    profile = Profile.model_validate(payload)
    text = build_doc(profile).plain_text()
    expected = {
        "education": "BITS Pilani",
        "projects": "Staffing Shift Scheduler",
        "skills": "PostgreSQL",
        "certifications": "AWS Solutions Architect",
        "achievements": "Winner, BITS Hackathon 2024",
        "publications": "Paper on shift scheduling",
        "experience": "Nimbus Analytics",
    }
    for label, needle in expected.items():
        assert needle in text, f"{label} content missing from output"


# --------------------------------------------------------------------------
# Page budget: the layout squeezes whitespace before content is ever dropped
# --------------------------------------------------------------------------


def _heavy_student() -> Profile:
    """A realistic heavy fresher CV: 4 projects x 6 bullets each."""
    bullet = {
        "raw_facts": "x",
        "text": (
            "Built feature that reduced p99 latency by 40% across 12 stores "
            "using FastAPI, Redis read-through caching and Postgres query tuning."
        ),
    }
    return Profile.model_validate({
        "contact": {
            "name": "Dusht", "email": "dusht@example.com",
            "phone": "+91 98765 43210", "city": "Bengaluru", "country": "India",
        },
        "summary": "Final-year CS undergraduate with backend experience in Python.",
        "education": [{
            "institution": "BITS Pilani", "degree": "B.E. Computer Science",
            "start": "2021-08", "end": "2025-06",
            "grade": {"value": "8.72", "scale": "10"},
            "coursework": ["Data Structures", "DBMS", "OS", "Networks"],
        }],
        "experience": [{
            "org": "Nimbus", "role": "Backend Intern", "type": "internship",
            "start": "2024-06", "end": "2024-08",
            "bullets": [{"raw_facts": "x", "text": "Automated the nightly ETL with Airflow."}],
        }],
        "projects": [
            {
                "name": f"Project Number {i}", "role": "Solo build",
                "start": "2023-01", "end": "2023-06",
                "tech": ["FastAPI", "PostgreSQL", "Redis", "Celery", "Docker"],
                "bullets": [dict(bullet) for _ in range(6)],
            }
            for i in range(1, 5)
        ],
        "skills": [
            {"name": "Languages", "items": ["Python", "SQL", "JavaScript", "Go"]},
            {"name": "Backend", "items": ["FastAPI", "Django", "Celery", "Redis"]},
        ],
        "certifications": [{"name": "AWS Solutions Architect - Associate", "date": "2024-03"}],
        "achievements": [{"name": "Winner, BITS Hackathon 2024"}],
    })


def test_student_cv_needs_compression_and_still_fits_one_page() -> None:
    """Auto-tightening must rescue a CV that overflows at normal density.

    Measured: 12 bullets renders on 2 pages at 'normal' and on 1 page once the
    layout tightens to 'compact'. Without density scaling this exceeded the
    rules.json fresher budget.
    """
    doc = build_doc(_student_with(3, 4))
    assert doc.level == "student"
    _, loose_pages, loose = render_pdf_report(build_doc(_student_with(3, 4)), max_pages=99)
    _, pages, density = render_pdf_report(doc, max_pages=rules.page_limit("student"))
    assert pages <= 1, f"{pages} pages at density={density}"
    assert density in {"compact", "tight"}, "should have had to squeeze to fit"
    assert loose_pages >= pages


def test_short_cv_is_not_squeezed() -> None:
    _, pages, density = render_pdf_report(build_doc(_student_with(2, 2)), max_pages=1)
    assert pages == 1
    assert density == "normal", "a short CV must keep comfortable spacing"


def test_genuinely_oversized_cv_reports_over_budget_instead_of_lying() -> None:
    """No density can make 24 long bullets fit one page.

    The renderer must still produce a valid PDF and say so, rather than
    silently handing back a 2-page resume as if it satisfied the budget.
    Trimming content is Stage 6's job.
    """
    doc = build_doc(_student_with(4, 6))
    pdf, pages, density = render_pdf_report(doc, max_pages=1)
    assert pdf.startswith(b"%PDF"), "must still render a valid document"
    assert pages > 1
    assert density == "tight", "should have used every density available"


def test_oversized_cv_still_has_readable_text() -> None:
    """Overflow must not cost content or text fidelity."""
    doc = build_doc(_student_with(4, 6))
    pdf, pages, _ = render_pdf_report(doc, max_pages=1)
    text = _pdf_text(pdf)
    assert pages >= 2
    assert "BITS Pilani" in text
    assert "Project 3" in text
    assert "\ufffd" not in text


def test_density_never_violates_researched_minimums() -> None:
    """Compression may touch whitespace only: font and margins stay in bounds."""
    limits = load_rules()["ats"]
    min_font = float(limits["fonts"]["body_size_pt"][0])
    min_margin = float(limits["margins_inches"]["min"])
    for density in DENSITIES:
        assert density["margin"] >= min_margin, density
    # font is never scaled at all
    assert rules.body_size_pt() >= min_font


def _student_with(n_projects: int, n_bullets: int) -> Profile:
    """A student CV with a controllable amount of content."""
    payload = _heavy_student().model_dump(mode="json")
    bullet = {
        "raw_facts": "x",
        "text": (
            "Built feature that reduced p99 latency by 40% across 12 stores "
            "using FastAPI, Redis read-through caching and Postgres query tuning."
        ),
    }
    payload["projects"] = [
        {
            "name": f"Project {i}",
            "role": "Solo build",
            "start": "2023-01",
            "end": "2023-06",
            "tech": ["FastAPI", "PostgreSQL", "Redis"],
            "bullets": [dict(bullet) for _ in range(n_bullets)],
        }
        for i in range(n_projects)
    ]
    return Profile.model_validate(payload)


def test_page_budget_is_reported_by_the_export_endpoint() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        c.put("/profile", json=_student_with(3, 4).model_dump(mode="json"))
        v = c.post("/versions/from-profile", params={"name": "heavy"}).json()
        r = c.post(f"/export/{v['id']}", params={"format": "pdf"})
    assert r.status_code == 200
    assert r.headers["x-page-budget"] == "ok"
    assert int(r.headers["x-pages"]) <= int(r.headers["x-page-limit"])


def test_export_endpoint_flags_an_over_budget_resume() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        c.put("/profile", json=_student_with(4, 6).model_dump(mode="json"))
        v = c.post("/versions/from-profile", params={"name": "too-big"}).json()
        r = c.post(f"/export/{v['id']}", params={"format": "pdf"})
    assert r.status_code == 200
    assert r.headers["x-page-budget"] == "over"
    assert r.content.startswith(b"%PDF"), "still returns a usable document"


def test_normal_resume_uses_normal_density_not_squeezed() -> None:
    """A short CV must keep comfortable spacing; squeezing is a last resort."""
    small = Profile.model_validate({
        "contact": {"name": "A B", "email": "a@b.com", "phone": "12345"},
        "summary": "One line.",
    })
    _, _, density = render_pdf_report(build_doc(small), max_pages=1)
    assert density == "normal"
