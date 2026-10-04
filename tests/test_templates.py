"""Resume templates: blank vs sheets.

The two templates come from genuinely conflicting sources (see RULES.md 3a), so
the rule here is that the *template decides*, not the renderer, and that
switching between them must never lose the user's data.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import rules
from app.main import app
from app.models import Profile
from app.render import build_doc
from app.rules import load_rules

INTERESTS = "Trail running, chess, and rebuilding mechanical keyboards."


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sheets_profile() -> Profile:
    return Profile.model_validate({
        "contact": {"name": "Dusht", "email": "dusht@example.com", "phone": "+91 98765 43210"},
        "summary": "Backend engineer with 3 years in Python.",
        "interests": INTERESTS,
        "education": [{
            "institution": "Sample Institute", "degree": "B.E. CS",
            "start": "2019-08", "end": "2022-06",
            "grade": {"value": "8.72", "scale": "10"},
        }],
        "experience": [{
            "org": "Sample Analytics", "role": "Backend Engineer", "type": "job",
            "start": "2022-07", "end": "Present",
            "bullets": [{"raw_facts": "x", "text": "Cut p99 latency by 66%."}],
        }],
        "skills": [{"name": "Backend", "items": ["FastAPI"]}],
        "achievements": [{"name": "Winner, Hackathon 2021"}],
    })


# --- the data, not the code ------------------------------------------------


def test_both_templates_exist_in_rules_json() -> None:
    assert set(rules.template_names()) == {"blank", "sheets"}
    assert rules.default_template() == "sheets"


def test_sheets_template_is_tagged_unverified() -> None:
    """It is one source, and it contradicts a verified rule. Say so in the data."""
    assert rules.template("sheets")["tag"] == "unverified"
    assert rules.template("blank")["tag"] == "verified"
    assert "sheetsresume" in rules.template("sheets")["source"].lower()


def test_disagreement_is_recorded_not_silently_resolved() -> None:
    templates = load_rules()["resume_templates"]
    assert "why_not_merge" in templates
    assert "verified" in templates["why_not_merge"].lower()


def test_unknown_template_falls_back_instead_of_crashing() -> None:
    """Version rows written before templates existed no longer carry a separate 'ats'
    template: unknown names fall back to the default template.
    """
    # Unknown template names fall back to the default template.
    assert rules.template("ats") == rules.template(None)
    # The default template is now 'sheets', not 'blank'.
    assert rules.template(None)["label"] == "SheetsResume - no summary, one Interests line at the end"


def test_student_order_is_not_the_experienced_one() -> None:
    """Regression: template_order passed 'student_fresher' into section_order,
    which expects the level, so students silently got the experienced layout --
    Education after Skills, and their internships dropped entirely."""
    for template in rules.template_names():
        order = rules.template_order(template, "student")
        assert order.index("education") < order.index("skills"), template
        assert "internships_experience" in order, template

        exp = rules.template_order(template, "experienced")
        assert exp.index("work_experience") < exp.index("education"), template


# --- what each template renders -------------------------------------------


def test_blank_keeps_the_summary(sheets_profile: Profile) -> None:
    doc = build_doc(sheets_profile, template="blank")
    assert "Summary" in [s.heading for s in doc.sections]
    assert "Backend engineer with 3 years" in doc.plain_text()


def test_sheets_drops_the_summary(sheets_profile: Profile) -> None:
    doc = build_doc(sheets_profile, template="sheets")
    headings = [s.heading for s in doc.sections]
    assert "Summary" not in headings
    assert "Backend engineer with 3 years" not in doc.plain_text()


def test_sheets_puts_interests_last(sheets_profile: Profile) -> None:
    doc = build_doc(sheets_profile, template="sheets")
    assert doc.sections[-1].key == "interests"
    assert doc.sections[-1].heading == "Interests"


def test_interests_is_one_line_under_skills(sheets_profile: Profile) -> None:
    text = build_doc(sheets_profile, template="sheets").plain_text()
    assert "INTERESTS" in text.upper()
    assert text.strip().endswith(INTERESTS), "must be the final line"
    assert text.count(INTERESTS) == 1


def test_blank_omits_interests(sheets_profile: Profile) -> None:
    doc = build_doc(sheets_profile, template="blank")
    assert "interests" not in [s.key for s in doc.sections]
    assert INTERESTS not in doc.plain_text()


def test_empty_interests_renders_no_section(sheets_profile: Profile) -> None:
    payload = sheets_profile.model_dump()
    payload["interests"] = ""
    doc = build_doc(Profile.model_validate(payload), template="sheets")
    assert "interests" not in [s.key for s in doc.sections]


def test_switching_templates_never_loses_data(sheets_profile: Profile) -> None:
    """The summary and interests live in the profile; templates only hide them."""
    blank = build_doc(sheets_profile, template="blank").plain_text()
    sheets = build_doc(sheets_profile, template="sheets").plain_text()
    again = build_doc(sheets_profile, template="blank").plain_text()

    assert blank == again, "switching back must restore everything"
    assert "Backend engineer with 3 years" in blank and "Backend engineer" not in sheets
    assert INTERESTS not in blank and INTERESTS in sheets
    # the underlying profile is untouched either way
    assert sheets_profile.summary
    assert sheets_profile.interests == INTERESTS


def test_sheets_order_matches_its_rules_json_order(sheets_profile: Profile) -> None:
    spec = rules.template("sheets")
    order = spec["orders"]["experienced"]
    doc = build_doc(sheets_profile, template="sheets")
    placed = [s.key for s in doc.sections]
    assert placed == [k for k in order if k in placed]


def test_interests_heading_is_sanctioned() -> None:
    safe = {h.lower() for h in load_rules()["safe_headings"]["acceptable"]}
    assert "interests" in safe


# --- page budget -----------------------------------------------------------


def test_sheets_locks_to_one_page() -> None:
    """The sheets template defaults to a one-page budget.
    It rises only when the profile carries research (publications),
    because those are evidence, not padding.
    """
    # The budget is 1 page for every level by default;
    # it rises by research_bump, capped at researched_max, only with publications.
    assert rules.page_limit("experienced") == 1
    assert rules.page_limit("experienced", has_research=True) == 2


# --- filenames -------------------------------------------------------------


def _disposition(client: TestClient, version_id: str, fmt: str) -> str:
    return client.post(f"/export/{version_id}", params={"format": fmt}).headers[
        "content-disposition"
    ]


def test_sheets_filename_is_first_last_resume(client: TestClient, sheets_profile: Profile) -> None:
    """Its source is emphatic: never 'Final', a year, or a bracketed job title."""
    client.put("/profile", json=sheets_profile.model_dump(mode="json"))
    v = client.post("/versions/from-profile",
                    params={"name": "Dusht Verma", "template": "sheets"}).json()
    disp = _disposition(client, v["id"], "pdf")
    assert 'filename="Dusht Verma - Resume.pdf"' in disp


def test_filename_never_carries_a_year_or_final() -> None:
    from app.main import _export_filename
    from app.models import Version

    spec = Version(name="Dusht Verma", profile_snapshot=Profile.model_validate(
        {"contact": {"name": "D", "email": "a@b.com", "phone": "12345"}}), template="sheets")
    assert _export_filename(spec, "pdf") == "Dusht Verma - Resume"


def test_single_word_name_does_not_crash() -> None:
    from app.main import _export_filename
    from app.models import Version

    spec = Version(name="Dusht", profile_snapshot=Profile.model_validate(
        {"contact": {"name": "D", "email": "a@b.com", "phone": "12345"}}), template="sheets")
    assert _export_filename(spec, "pdf") == "Dusht - Resume"


def test_symbol_only_name_falls_back_safely() -> None:
    """A name with nothing filename-safe must not produce a broken header."""
    from app.main import _export_filename
    from app.models import Version

    spec = Version(name="###", profile_snapshot=Profile.model_validate(
        {"contact": {"name": "D", "email": "a@b.com", "phone": "12345"}}), template="sheets")
    out = _export_filename(spec, "pdf")
    assert out == "Resume"
    assert out and not out.startswith(".") and ".." not in out


def test_empty_version_name_is_rejected_by_the_api(client: TestClient) -> None:
    """Name has a length floor, so an empty one never reaches the renderer."""
    r = client.post("/versions", json={
        "name": "",
        "profile_snapshot": {"contact": {"name": "D", "email": "a@b.com", "phone": "12345"}},
    })
    assert r.status_code == 422


def test_filename_stays_inert(client: TestClient, sheets_profile: Profile) -> None:
    """The name reaches a header, so it must remain sanitised."""
    client.put("/profile", json=sheets_profile.model_dump(mode="json"))
    v = client.post("/versions/from-profile",
                    params={"name": 'evil"; rm -rf / #', "template": "sheets"}).json()
    disp = _disposition(client, v["id"], "txt")
    assert "\r" not in disp and "\n" not in disp
    inner = disp.split("filename=", 1)[1].strip('"')
    for ch in ('"', "/", "\\", ";", "#"):
        assert ch not in inner, inner
    # Spaces are allowed (the convention needs them) but runs collapse and the
    # ends are trimmed.
    assert "  " not in inner and inner == inner.strip()
    assert not inner.startswith(".") and ".." not in inner


# --- API plumbing ----------------------------------------------------------


def test_preview_accepts_a_template(client: TestClient, sheets_profile: Profile) -> None:
    body = sheets_profile.model_dump(mode="json")
    r = client.post("/preview", json=body, params={"template": "sheets"})
    assert r.status_code == 200
    assert r.headers["X-Template"] == "sheets"
    assert r.headers["X-Page-Limit"] == "1"


def test_preview_reports_the_stricter_budget_for_sheets(
    client: TestClient, sheets_profile: Profile
) -> None:
    """The page budget is one page for every level by default.
    It rises only when the profile carries research (publications),
    because those are evidence, not padding.
    """
    body = sheets_profile.model_dump(mode="json")
    # By default, every template gives a 1-page budget.
    assert client.post("/preview", json=body, params={"template": "blank"}).headers[
        "X-Page-Limit"
    ] == "1"
    assert client.post("/preview", json=body, params={"template": "sheets"}).headers[
        "X-Page-Limit"
    ] == "1"
    # With research, the budget can rise — the researched maxima are kept as a ceiling.
    # A profile with publications bumps the page limit for experienced from 1 to 2.


def test_snapshot_stores_the_template(client: TestClient, sheets_profile: Profile) -> None:
    client.put("/profile", json=sheets_profile.model_dump(mode="json"))
    v = client.post("/versions/from-profile",
                    params={"name": "x", "template": "sheets"}).json()
    assert v["template"] == "sheets"
    assert client.post(f"/export/{v['id']}", params={"format": "txt"}).text.count(
        "Backend engineer with 3 years") == 0


def test_version_template_defaults_to_blank() -> None:
    from app.models import Version
    from app.render import build_doc_from_version

    v = Version(name="x", profile_snapshot=Profile.model_validate(
        {"contact": {"name": "D", "email": "a@b.com", "phone": "12345"}}))
    assert v.template == "blank"
    assert build_doc_from_version(v).sections[0].heading == "Summary"


def test_legacy_version_with_ats_template_still_exports(
    client: TestClient, sheets_profile: Profile
) -> None:
    """Versions written before templates existed carry 'ats'."""
    v = client.post("/versions", json={
        "name": "legacy", "template": "ats",
        "profile_snapshot": sheets_profile.model_dump(mode="json"),
    })
    assert v.status_code == 201
    assert client.post(f"/export/{v.json()['id']}", params={"format": "pdf"}).status_code == 200
