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
