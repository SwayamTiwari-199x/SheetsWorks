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


@pytest.fixture
def seeded(client: TestClient, sample_profile_payload: dict) -> str:
    client.put("/profile", json=sample_profile_payload)
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
    assert "Aditi Sharma" in text
    assert "aditi.sharma@example.com" in text


def test_export_pdf_reports_page_count_and_limit(client: TestClient, seeded: str) -> None:
    r = client.post(f"/export/{seeded}", params={"format": "pdf"})
    pages = int(r.headers["x-pages"])
    assert pages >= 1
    assert int(r.headers["x-page-limit"]) == 2  # experienced


def test_export_headers_expose_density_and_budget(
    client: TestClient, seeded: str
) -> None:
    r = client.post(f"/export/{seeded}", params={"format": "pdf"})
    assert r.headers["x-density"] in {"normal", "compact", "tight"}
    assert r.headers["x-page-budget"] == "ok"


def test_experienced_limit_is_two_pages(client: TestClient, seeded: str) -> None:
    r = client.post(f"/export/{seeded}", params={"format": "pdf"})
    assert int(r.headers["x-page-limit"]) == 2


def test_export_docx_opens_with_python_docx(client: TestClient, seeded: str) -> None:
    r = client.post(f"/export/{seeded}", params={"format": "docx"})
    d = DocxDocument(io.BytesIO(r.content))
    assert any("Aditi Sharma" in p.text for p in d.paragraphs)


def test_export_txt_is_plain_text(client: TestClient, seeded: str) -> None:
    r = client.post(f"/export/{seeded}", params={"format": "txt"})
    assert "Aditi Sharma" in r.text
    assert "\x00" not in r.text


def test_export_filename_is_sanitised(client: TestClient, seeded: str) -> None:
    """The name reaches a Content-Disposition header, so it must be inert."""
    client.put("/profile", json={"contact": {
        "name": "Aditi Sharma", "email": "a@b.com", "phone": "12345"}})
    v = client.post("/versions/from-profile", params={"name": 'evil"; rm -rf / #.txt'}).json()
    r = client.post(f"/export/{v['id']}", params={"format": "txt"})
    disp = r.headers["content-disposition"]

    assert "\r" not in disp and "\n" not in disp
    # The quotes in the header are our own delimiters; the *value* must be inert.
    inner = disp.split("filename=", 1)[1].strip('"')
    for ch in ('"', "/", "\\", ";", " ", "#"):
        assert ch not in inner, f"{ch!r} survived into the filename: {inner!r}"
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
    client.put("/profile", json=sample_profile_payload)
    assert client.post("/export/nope").status_code == 404


# --- personal details stay opt-in ----------------------------------------


def test_personal_details_are_off_by_default(client: TestClient, sample_profile_payload: dict) -> None:
    payload = dict(sample_profile_payload)
    payload["personal_details"] = {"gender": "Female", "date_of_birth": "2001-04-02"}
    client.put("/profile", json=payload)
    v = client.post("/versions/from-profile", params={"name": "off"}).json()
    text = client.post(f"/export/{v['id']}", params={"format": "txt"}).text
    assert "Female" not in text
    assert "2001-04-02" not in text


def test_personal_details_render_when_opted_in(
    client: TestClient, sample_profile_payload: dict
) -> None:
    payload = dict(sample_profile_payload)
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
