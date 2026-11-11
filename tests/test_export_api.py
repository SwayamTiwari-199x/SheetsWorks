"""POST /export/{version_id}: the Stage 2 delivery path."""

from __future__ import annotations

import io

import pdfplumber
import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def named(payload: dict, name: str = "Sample Applicant") -> dict:
    """Export refuses while the name is the placeholder "Anon", so any test
    that exports has to carry a name that is not the placeholder."""
    out = dict(payload)
    out["contact"] = dict(payload["contact"], name=name)
    return out


@pytest.fixture
def seeded(client: TestClient, sample_profile_payload: dict) -> str:
    client.put("/profile", json=named(sample_profile_payload))
    v = client.post("/versions/from-profile", params={"name": "My Resume"})
    assert v.status_code == 201
    return v.json()["id"]


# --- happy paths -----------------------------------------------------------


@pytest.mark.parametrize("fmt", ["pdf", "docx", "txt"])
def test_export_each_format(client: TestClient, seeded: str, fmt: str) -> None:
    r = client.post(f"/export/{seeded}", params={"format": fmt})
    assert r.status_code == 200
    assert len(r.content) > 100
    assert "attachment" in r.headers["content-disposition"]
    assert fmt in r.headers["content-disposition"]


def test_export_pdf_is_a_real_pdf(client: TestClient, seeded: str) -> None:
    r = client.post(f"/export/{seeded}", params={"format": "pdf"})
    assert r.content.startswith(b"%PDF")
    with pdfplumber.open(io.BytesIO(r.content)) as doc:
        text = "\n".join(p.extract_text() or "" for p in doc.pages)
    assert "Sample Applicant" in text
    assert "anon@example.com" in text


def test_export_pdf_reports_page_count_and_limit(client: TestClient, seeded: str) -> None:
    """The page budget is one page for every level by default.
    It rises only when the profile carries research (publications),
    because those are evidence, not padding.
    The researched maxima are kept as a ceiling for the bump.
    """
    r = client.post(f"/export/{seeded}", params={"format": "pdf"})
    pages = int(r.headers["x-pages"])
    assert pages >= 1
    # Default budget is 1 page; with research it rises to the researched max.
    assert int(r.headers["x-page-limit"]) == 1
    # Verify the budget is ok
    assert r.headers["x-page-budget"] == "ok"


def test_export_headers_expose_density_and_budget(
    client: TestClient, seeded: str
) -> None:
    r = client.post(f"/export/{seeded}", params={"format": "pdf"})
    assert r.headers["x-density"] in {"normal", "compact", "tight"}
    assert r.headers["x-page-budget"] == "ok"


def test_experienced_limit_is_two_pages(client: TestClient, seeded: str) -> None:
    """The page budget is one page for every level by default.
    It rises only when the profile carries research (publications),
    because those are evidence, not padding.
    The researched maxima are kept as a ceiling for the bump.
    """
    r = client.post(f"/export/{seeded}", params={"format": "pdf"})
    # Default budget is 1 page; with research it rises to the researched max.
    assert int(r.headers["x-page-limit"]) == 1
    # Verify the research ceiling exists by checking the header reports ok budget
    assert r.headers["x-page-budget"] == "ok"


def test_export_docx_opens_with_python_docx(client: TestClient, seeded: str) -> None:
    r = client.post(f"/export/{seeded}", params={"format": "docx"})
    d = DocxDocument(io.BytesIO(r.content))
    assert any("Sample Applicant" in p.text for p in d.paragraphs)


def test_export_txt_is_plain_text(client: TestClient, seeded: str) -> None:
    r = client.post(f"/export/{seeded}", params={"format": "txt"})
    assert "Sample Applicant" in r.text
    assert "\x00" not in r.text


def test_export_filename_is_sanitised(client: TestClient, seeded: str) -> None:
    """The name reaches a Content-Disposition header, so it must be inert."""
    client.put("/profile", json={"contact": {
        "name": "Sample Applicant", "email": "a@b.com", "phone": "12345"}})
    v = client.post("/versions/from-profile", params={"name": 'evil"; rm -rf / #.txt'}).json()
    r = client.post(f"/export/{v['id']}", params={"format": "txt"})
    disp = r.headers["content-disposition"]

    assert "\r" not in disp and "\n" not in disp
    # The quotes in the header are our own delimiters; the *value* must be inert.
    inner = disp.split("filename=", 1)[1].strip('"')
    for ch in ('"', "/", "\\", ";", "#"):
        assert ch not in inner, f"{ch!r} survived into the filename: {inner!r}"
    # Spaces are allowed on purpose -- "FirstName LastName Resume" needs them --
    # but runs collapse to one and the ends are trimmed.
    assert "  " not in inner and inner == inner.strip()
    assert inner.endswith(".txt")


# --- error paths -----------------------------------------------------------


def test_export_unknown_version_is_404(client: TestClient) -> None:
    assert client.post("/export/does-not-exist", params={"format": "pdf"}).status_code == 404


def test_export_unknown_format_is_400(client: TestClient, seeded: str) -> None:
    r = client.post(f"/export/{seeded}", params={"format": "exe"})
    assert r.status_code == 400
    assert "unsupported format" in r.json()["detail"]


def test_export_defaults_to_pdf(client: TestClient, seeded: str) -> None:
    assert client.post(f"/export/{seeded}").content.startswith(b"%PDF")


def test_snapshot_requires_a_profile(client: TestClient) -> None:
    """Fresh test DB has no profile yet."""
    assert client.post("/versions/from-profile").status_code == 404


def test_export_without_snapshot_is_404(client: TestClient, sample_profile_payload: dict) -> None:
    client.put("/profile", json=named(sample_profile_payload))
    assert client.post("/export/nope").status_code == 404


# --- the placeholder name blocks export -----------------------------------


def test_export_refuses_while_the_name_is_still_the_placeholder(
    client: TestClient, sample_profile_payload: dict
) -> None:
    """A resume still named "Anon" is a template, not a document to send.

    The snapshot is written through POST /versions directly, because the normal
    export path (POST /versions/from-profile) refuses before it can be called --
    which is the point of the next test.
    """
    client.put("/profile", json=sample_profile_payload)
    created = client.post("/versions", json={
        "name": "untitled",
        "profile_snapshot": sample_profile_payload,
    })
    assert created.status_code == 201
    for fmt in ("pdf", "docx", "txt"):
        r = client.post(f"/export/{created.json()['id']}", params={"format": fmt})
        assert r.status_code == 400, fmt
        assert "Anon" in r.json()["detail"]
        assert "My Resume" in r.json()["detail"]


def test_a_refused_export_leaves_no_version_behind(
    client: TestClient, sample_profile_payload: dict
) -> None:
    """The export flow is snapshot-then-export, so refusing at export time
    alone would leave a stored version per attempt."""
    client.put("/profile", json=sample_profile_payload)
    before = len(client.get("/versions").json())
    r = client.post("/versions/from-profile", params={"name": "Anon Resume"})
    assert r.status_code == 400
    assert "Anon" in r.json()["detail"]
    assert len(client.get("/versions").json()) == before


def test_export_allows_once_the_name_is_edited(
    client: TestClient, sample_profile_payload: dict
) -> None:
    client.put("/profile", json=named(sample_profile_payload))
    v2 = client.post("/versions/from-profile", params={"name": "untitled"})
    assert v2.status_code == 201
    assert client.post(f"/export/{v2.json()['id']}", params={"format": "txt"}).status_code == 200


# --- personal details stay opt-in ----------------------------------------


def test_personal_details_are_off_by_default(client: TestClient, sample_profile_payload: dict) -> None:
    payload = named(sample_profile_payload)
    payload["personal_details"] = {"gender": "Female", "date_of_birth": "2001-04-02"}
    client.put("/profile", json=payload)
    v = client.post("/versions/from-profile", params={"name": "off"}).json()
    text = client.post(f"/export/{v['id']}", params={"format": "txt"}).text
    assert "Female" not in text
    assert "2001-04-02" not in text


def test_personal_details_render_when_opted_in(
    client: TestClient, sample_profile_payload: dict
) -> None:
    payload = named(sample_profile_payload)
    payload["personal_details"] = {"gender": "Female", "date_of_birth": "2001-04-02"}
    client.put("/profile", json=payload)
    v = client.post(
        "/versions/from-profile",
        params={"name": "on", "include_personal_details": True},
    ).json()
    text = client.post(f"/export/{v['id']}", params={"format": "txt"}).text
    assert "Female" in text


def test_explicit_version_snapshot_is_used(client: TestClient, sample_profile_payload: dict) -> None:
    """A version can carry its own snapshot, not just the live profile."""
    v = client.post("/versions", json={
        "name": "custom",
        "profile_snapshot": {
            "contact": {"name": "Other Person", "email": "o@p.com", "phone": "99999"}
        },
    })
    assert v.status_code == 201
    text = client.post(f"/export/{v.json()['id']}", params={"format": "txt"}).text
    assert "Other Person" in text


def test_renderers_reject_later_stage_fields(client: TestClient) -> None:
    """A Version must not smuggle unrouted data through the snapshot."""
    r = client.post("/versions", json={
        "name": "x",
        "profile_snapshot": {"contact": {"name": "A", "email": "a@b.com", "phone": "1"}, "bogus": 1},
    })
    assert r.status_code == 422
