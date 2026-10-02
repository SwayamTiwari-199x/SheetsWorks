"""Security regressions found by probing the live API.

Each test pins a defect that was actually observed, so it cannot come back.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import Experience, Profile


def contact(**kw) -> dict:
    base = {"name": "Aditi Sharma", "email": "aditi@example.com", "phone": "+91 98765 43210"}
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
