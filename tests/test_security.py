"""Security regressions found by probing the live API.

Each test pins a defect that was actually observed, so it cannot come back.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import Experience, Profile
from app.render import build_doc, render_docx, render_pdf, render_txt


def contact(**kw) -> dict:
    base = {"name": "Dusht", "email": "dusht@example.com", "phone": "+91 98765 43210"}
    base.update(kw)
    return base


# --- 1. SQL injection -----------------------------------------------------
# db.py uses parameterised queries, so these must be stored as inert text.


@pytest.mark.parametrize(
    "payload",
    [
        "'; DROP TABLE profile; --",
        "' OR '1'='1",
        "1); DELETE FROM profile; --",
        "%' UNION SELECT body FROM sqlite_master --",
    ],
)
def test_sql_injection_payloads_are_stored_as_text(payload: str) -> None:
    with TestClient(app) as client:
        r = client.put("/profile", json={"contact": contact(name=payload)})
        assert r.status_code == 200
        assert r.json()["contact"]["name"] == payload
        # table still exists and is queryable
        assert client.get("/profile").status_code == 200


# --- 2. Invisible / control characters ------------------------------------


@pytest.mark.parametrize(
    "char,label",
    [
        ("\x00", "NUL"),
        ("\u202e", "RTL override"),
        ("\u200b", "zero-width space"),
        ("\u2066", "bidi isolate"),
        ("\ufeff", "BOM"),
        ("\x7f", "DEL"),
    ],
)
def test_invisible_characters_are_rejected(char: str, label: str) -> None:
    with TestClient(app) as client:
        r = client.put("/profile", json={"contact": contact(name=f"A{char}B")})
    assert r.status_code == 422, f"{label} should be rejected"
    assert "U+" in r.text


def test_tab_and_newline_still_allowed() -> None:
    """Multi-line text is legitimate and must not be blocked."""
    payload = {"contact": contact(), "summary": "line one\nline two\twith tab"}
    with TestClient(app) as client:
        r = client.put("/profile", json=payload)
    assert r.status_code == 200


def test_normal_unicode_is_allowed() -> None:
    """Accents and non-Latin scripts are normal in Indian resumes."""
    with TestClient(app) as client:
        r = client.put("/profile", json={"contact": contact(name="Ramesh Iyer", city="Kochi")})
        r2 = client.put("/profile", json={"contact": contact(name="José Müller", city="Zürich")})
        r3 = client.put("/profile", json={"contact": contact(name="अदिति शर्मा", city="पुणे")})
    for resp in (r, r2, r3):
        assert resp.status_code == 200


# --- 3. Unbounded lists ---------------------------------------------------


def test_absurdly_long_list_is_rejected() -> None:
    """A resume has a finite number of entries."""
    payload = {"contact": contact(), "achievements": [{"name": f"a{i}"} for i in range(500)]}
    with TestClient(app) as client:
        r = client.put("/profile", json=payload)
    assert r.status_code == 422


def test_bullet_count_is_capped() -> None:
    bullets = [{"text": f"did thing {i}"} for i in range(40)]
    exp = {"org": "X", "role": "Y", "start": "2022-01", "end": "Present", "bullets": bullets}
    with pytest.raises(ValidationError):
        Experience.model_validate(exp)


# --- 4. Deep nesting caused a 500 with a traceback ------------------------


def test_deeply_nested_body_returns_422_not_500() -> None:
    raw = b'{"contact":' + b"[" * 3000 + b"]" * 3000 + b"}"
    with TestClient(app) as client:
        r = client.put(
            "/profile", content=raw, headers={"Content-Type": "application/json"}
        )
    assert r.status_code == 422, "over-nested body must not produce a 500"


# --- 5. DNS rebinding via Host header -------------------------------------


def test_foreign_host_header_is_rejected() -> None:
    with TestClient(app) as client:
        r = client.get("/health", headers={"Host": "evil.example.com"})
    assert r.status_code == 400


def test_localhost_still_allowed() -> None:
    with TestClient(app) as client:
        assert client.get("/health", headers={"Host": "localhost:8000"}).status_code == 200
        assert client.get("/health", headers={"Host": "127.0.0.1:8000"}).status_code == 200


# --- 6. No CORS is configured (deliberate) --------------------------------


def test_no_cors_headers_are_emitted() -> None:
    """CORS must stay off: this app has no auth and no need for cross-origin access."""
    with TestClient(app) as client:
        r = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# --- 7. XSS payloads are stored verbatim, not sanitised -------------------
# This is correct at the API layer (the data is the user's own). It is a hard
# requirement that Stage 3's frontend never assigns profile data to innerHTML.


def test_html_is_not_escaped_or_sanitised_in_storage() -> None:
    payload = "<script>alert(1)</script>"
    with TestClient(app) as client:
        r = client.put("/profile", json={"contact": contact(name=payload)})
    assert r.status_code == 200
    assert r.json()["contact"]["name"] == payload


def test_photo_path_is_stored_verbatim_not_resolved() -> None:
    """Traversal strings are data. A renderer must never open this path."""
    with TestClient(app) as client:
        r = client.put(
            "/profile",
            json={"contact": contact(), "personal_details": {"photo_path": "../../etc/passwd"}},
        )
    assert r.status_code == 200
    assert r.json()["personal_details"]["photo_path"] == "../../etc/passwd"


# --- 8. Secrets must never leak through the API --------------------------


def test_profile_response_contains_no_secrets() -> None:
    with TestClient(app) as client:
        client.put("/profile", json={"contact": contact()})
        r = client.get("/profile")
    blob = r.text.lower()
    for needle in ("api_key", "apikey", "bearer", "authorization", "gemini", "groq", "mistral"):
        assert needle not in blob, f"response leaked {needle!r}"


# --------------------------------------------------------------------------
# Second security sweep: response headers, dead API surface, log injection,
# and unicode robustness in the renderers.
# --------------------------------------------------------------------------


def test_security_headers_present_on_success() -> None:
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_security_headers_present_on_404() -> None:
    with TestClient(app) as client:
        r = client.get("/profile")
    assert r.status_code == 404
    assert r.headers["x-content-type-options"] == "nosniff"


def test_security_headers_present_on_422() -> None:
    with TestClient(app) as client:
        r = client.put("/profile", json={})
    assert r.status_code == 422
    assert r.headers["x-content-type-options"] == "nosniff"


def test_export_sets_no_store() -> None:
    """Exports are personal documents; they must not sit in a shared cache."""
    with TestClient(app) as client:
        client.put("/profile", json={"contact": {
            "name": "A", "email": "a@b.com", "phone": "12345"}})
        v = client.post("/versions/from-profile").json()
        for fmt in ("pdf", "docx", "txt"):
            r = client.post(f"/export/{v['id']}", params={"format": fmt})
            assert r.headers["cache-control"] == "no-store", fmt


def test_export_has_no_dead_download_parameter() -> None:
    """`download` was accepted, documented and ignored."""
    with TestClient(app) as client:
        op = client.get("/openapi.json").json()["paths"]["/export/{version_id}"]["post"]
    names = [p["name"] for p in op.get("parameters", [])]
    assert "download" not in names
    assert "format" in names


def test_format_param_name_is_unchanged_for_callers() -> None:
    """The Python param is now `fmt`; the wire name must stay `format`."""
    with TestClient(app) as client:
        client.put("/profile", json={"contact": {
            "name": "A", "email": "a@b.com", "phone": "12345"}})
        v = client.post("/versions/from-profile").json()
        assert client.post(f"/export/{v['id']}?format=pdf").status_code == 200
        assert client.post(f"/export/{v['id']}?format=txt").status_code == 200


def test_filename_cannot_be_dot_only() -> None:
    """A name of '..' must not yield a filename like '...pdf'."""
    with TestClient(app) as client:
        client.put("/profile", json={"contact": {
            "name": "A", "email": "a@b.com", "phone": "12345"}})
        v = client.post("/versions/from-profile", params={"name": ".."}).json()
        r = client.post(f"/export/{v['id']}", params={"format": "txt"})
    inner = r.headers["content-disposition"].split("filename=", 1)[1].strip('"')
    assert inner == "Resume.txt", inner


@pytest.mark.parametrize(
    "label,value",
    [
        ("Devanagari", "\u0905\u0926\u093f\u0924\u093f \u0936\u0930\u094d\u092e\u093e"),
        ("CJK", "\u9648\u6653\u96ef"),
        ("Cyrillic", "\u0410\u043d\u043d\u0430 \u0418\u0432\u0430\u043d\u043e\u0432\u0430"),
        ("Arabic", "\u0623\u062d\u0645\u062f \u0639\u0644\u064a"),
        ("Hebrew", "\u05d3\u05d5\u05d3 \u05db\u05d4\u05df"),
        ("Greek", "\u0393\u03b9\u03ce\u03c1\u03b3\u03bf\u03c2"),
        ("Emoji", "Hire me \U0001f680"),
        ("Accents", "Jos\u00e9 M\u00fcller \u00c5ngstr\u00f6m"),
        ("Turkish", "\u015eeyma \u00c7a\u011flayan"),
    ],
)
def test_international_names_render_in_all_formats(label: str, value: str) -> None:
    """An Indian resume routinely mixes scripts; rendering must not choke."""
    profile = Profile.model_validate({
        "contact": {"name": value, "email": "a@b.com", "phone": "12345", "city": value},
        "summary": f"Engineer from {value}.",
        "experience": [{
            "org": value, "role": "Engineer", "start": "2022-01", "end": "Present",
            "bullets": [{"raw_facts": "x", "text": f"Shipped {value} for 40% of traffic."}],
        }],
    })
    doc = build_doc(profile)
    assert render_pdf(doc).startswith(b"%PDF")
    assert render_docx(doc)[:2] == b"PK"
    assert value.encode("utf-8") in render_txt(doc)


def test_log_sanitiser_strips_newlines() -> None:
    from app.main import _log_safe

    assert "\n" not in _log_safe("/profile%0A[FORGED] 2026-01-01 admin")
    assert "\r" not in _log_safe("/x\r\nInjected: yes")
    assert len(_log_safe("A" * 5000)) == 200
