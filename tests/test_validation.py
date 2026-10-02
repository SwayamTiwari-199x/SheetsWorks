"""Acceptance: invalid profiles are rejected with a clear error."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import Profile


def _minimal(**overrides) -> dict:
    payload = {
        "contact": {
            "name": "Dusht",
            "email": "dusht@example.com",
            "phone": "+91 98765 43210",
        }
    }
    payload.update(overrides)
    return payload


# --- model-level ---------------------------------------------------------


def test_missing_name_is_rejected() -> None:
    payload = _minimal()
    del payload["contact"]["name"]
    with pytest.raises(ValidationError) as exc:
        Profile.model_validate(payload)
    message = str(exc.value)
    assert "name" in message
    assert "contact" in message


def test_missing_email_is_rejected() -> None:
    payload = _minimal()
    del payload["contact"]["email"]
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


def test_missing_contact_block_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate({})


def test_bad_date_is_rejected() -> None:
    payload = _minimal(
        experience=[
            {"org": "PayFlow", "role": "Backend Engineer", "start": "banana", "end": "Present"}
        ]
    )
    with pytest.raises(ValidationError) as exc:
        Profile.model_validate(payload)
    assert "banana" in str(exc.value)
    assert "YYYY-MM" in str(exc.value)


def test_bad_date_day_is_rejected() -> None:
    payload = _minimal(
        education=[
            {"institution": "BITS Pilani", "start": "2022-13", "end": "2023-01"}
        ]
    )
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


def test_end_before_start_is_rejected() -> None:
    payload = _minimal(
        experience=[
            {"org": "PayFlow", "role": "Backend Engineer", "start": "2024-01", "end": "2023-01"}
        ]
    )
    with pytest.raises(ValidationError) as exc:
        Profile.model_validate(payload)
    assert "before" in str(exc.value)


def test_present_is_allowed_as_end_date() -> None:
    payload = _minimal(
        experience=[
            {"org": "PayFlow", "role": "Backend Engineer", "start": "2022-07", "end": "Present"}
        ]
    )
    assert Profile.model_validate(payload).experience[0].end == "Present"


def test_unknown_field_is_rejected() -> None:
    payload = _minimal()
    payload["headline"] = "nope"
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


def test_bad_email_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate(_minimal(contact={"name": "A", "email": "nope", "phone": "12345"}))


def test_bullet_text_is_required() -> None:
    payload = _minimal(
        experience=[
            {
                "org": "PayFlow",
                "role": "Backend Engineer",
                "start": "2022-07",
                "bullets": [{"raw_facts": "did a thing"}],
            }
        ]
    )
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


# --- HTTP-level ----------------------------------------------------------


def test_api_rejects_missing_name_with_field_path() -> None:
    payload = _minimal()
    del payload["contact"]["name"]
    with TestClient(app) as client:
        resp = client.put("/profile", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    loc = " ".join(str(part) for part in body["detail"][0]["loc"])
    assert "contact" in loc and "name" in loc


def test_api_rejects_bad_date_with_reason() -> None:
    payload = _minimal(
        experience=[
            {"org": "PayFlow", "role": "Backend Engineer", "start": "banana", "end": "Present"}
        ]
    )
    with TestClient(app) as client:
        resp = client.put("/profile", json=payload)
    assert resp.status_code == 422
    assert "banana" in resp.text


def test_api_rejects_empty_body() -> None:
    with TestClient(app) as client:
        assert client.put("/profile", json={}).status_code == 422


def test_rejected_put_does_not_persist() -> None:
    with TestClient(app) as client:
        client.put("/profile", json={"contact": {"email": "x@y.com"}})
        assert client.get("/profile").status_code == 404
