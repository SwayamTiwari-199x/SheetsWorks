"""Acceptance: PUT then GET a sample profile round-trips unchanged."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_profile_get_before_put_is_404() -> None:
    with TestClient(app) as client:
        assert client.get("/profile").status_code == 404


def test_profile_roundtrips_unchanged(sample_profile_payload: dict) -> None:
    with TestClient(app) as client:
        put = client.put("/profile", json=sample_profile_payload)
        assert put.status_code == 200

        get = client.get("/profile")
        assert get.status_code == 200

    # Byte-identical, including defaults the client never sent explicitly.
    assert get.json() == sample_profile_payload


def test_profile_roundtrips_twice_without_drift(sample_profile_payload: dict) -> None:
    with TestClient(app) as client:
        first = client.put("/profile", json=sample_profile_payload).json()
        second = client.put("/profile", json=first).json()
    assert first == second == sample_profile_payload


def test_profile_put_replaces_previous(sample_profile_payload: dict) -> None:
    with TestClient(app) as client:
        client.put("/profile", json=sample_profile_payload)
        trimmed = dict(sample_profile_payload)
        trimmed["summary"] = "Backend engineer."
        client.put("/profile", json=trimmed)
        got = client.get("/profile").json()
    assert got["summary"] == "Backend engineer."


def test_sample_profile_preserves_special_characters() -> None:
    """SPEC requires & % # _ $ to survive storage intact (Stage 2 renders them)."""
    payload = {
        "contact": {
            "name": "Anon",
            "email": "anon@example.com",
            "phone": "+91 98765 43210",
        },
        "experience": [
            {
                "org": "R&D (Labs)",
                "role": "Engineer",
                "start": "2022-07",
                "end": "Present",
                "bullets": [
                    {
                        "text": "Cut costs 100% & latency 40% #1 using C++/CLI_v2 $var",
                        "raw_facts": "cut costs 100% & latency 40% #1 using C++/CLI_v2 $var",
                    }
                ],
            }
        ],
    }
    with TestClient(app) as client:
        assert client.put("/profile", json=payload).status_code == 200
        got = client.get("/profile").json()

    assert got["experience"][0]["org"] == "R&D (Labs)"
    assert got["experience"][0]["bullets"][0]["text"] == (
        "Cut costs 100% & latency 40% #1 using C++/CLI_v2 $var"
    )
