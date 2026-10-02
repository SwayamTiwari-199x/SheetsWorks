"""Acceptance: FastAPI app starts and /docs loads."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_ok() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_docs_loads() -> None:
    with TestClient(app) as client:
        resp = client.get("/docs")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "swagger-ui" in resp.text.lower()


def test_openapi_schema_builds() -> None:
    with TestClient(app) as client:
        resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "/profile" in schema["paths"]
    assert {"get", "put"} <= set(schema["paths"]["/profile"])


def test_stage2_exposes_only_its_own_routes() -> None:
    """Stage 1+2 scope. Guards against speculative endpoints creeping back.

    Stage 2 legitimately adds the version snapshot and export routes because
    POST /export/{version_id} is required by BUILD_PLAN Stage 2 and needs a
    stored version to export. Everything else (validators, JD, applications,
    tailoring) belongs to a later stage and must stay absent.
    """
    with TestClient(app) as client:
        paths = set(client.get("/openapi.json").json()["paths"])
    assert paths == {
        "/health",
        "/profile",
        "/versions",
        "/versions/from-profile",
        "/export/{version_id}",
    }


def test_validate_stub_is_gone() -> None:
    with TestClient(app) as client:
        assert client.post("/validate/anything").status_code == 404


def test_later_stage_routes_are_absent() -> None:
    """Nothing from Stage 4-8 may exist yet."""
    with TestClient(app) as client:
        paths = set(client.get("/openapi.json").json()["paths"])
    for not_yet in ("/assist/{section}", "/jd/analyze", "/jd/gap", "/tailor",
                    "/applications", "/validate/{version_id}"):
        assert not_yet not in paths, f"{not_yet} belongs to a later stage"
