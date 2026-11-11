"""Shared fixtures: isolated temp DB per test, and a fake httpx client."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Point at a throwaway DB before app.config is imported anywhere.
os.environ["DATABASE_URL"] = "sqlite:///./test_resume.db"
os.environ["LOG_DIR"] = "logs"

# Scrubbed before anything imports app.config. pydantic-settings reads the
# process environment when Settings() is constructed rather than at import, so
# this is belt-and-braces -- but the list was hardcoded and a provider added to
# API_KEY_VARS was NOT added here, which leaked a real key into test output and
# into an assertion message. It is checked against API_KEY_VARS by
# test_every_provider_key_is_scrubbed so it cannot drift again.
_PRE_IMPORT_SCRUB = (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY",
)
for var in _PRE_IMPORT_SCRUB:
    os.environ.pop(var, None)

from app import config, db  # noqa: E402
from app.models import Profile  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: hits a real provider; only runs with RUN_LIVE_LLM=1"
    )

# Anything the developer's real environment might set. pydantic-settings always
# reads the process environment and `_env_file=None` does NOT disable that, so
# these must be cleared explicitly or tests become machine-dependent.
#
# The key vars come from API_KEY_VARS rather than being spelled out again. They
# were listed twice in this one file and a new provider had to be added to both
# by hand; one list missed it and a real OpenRouter key leaked into a test
# failure message.
_LLM_ENV_VARS = [
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_TOKENS",
    "LLM_TEMPERATURE",
] + list(config.API_KEY_VARS.values())


def scrub_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every ambient LLM variable, including all provider API keys.

    A plain function rather than fixture body code, because a test has to be able
    to call this and prove it works. pytest refuses direct fixture calls, and
    "the list looks right" is not evidence -- a real OpenRouter key was read by
    the suite and printed in an assertion message because openrouter had been
    added to API_KEY_VARS and not to this list.
    """
    for var in _LLM_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def isolated_llm_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Guarantee no test sees the real .env or an ambient LLM_* variable."""
    scrub_llm_env(monkeypatch)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


import socket as _socket

# Captured at import, before any fixture gets a chance to patch it. Holding the
# real function rather than calling `socket.socket.connect` from inside the guard
# would be calling the patched one.
_REAL_CONNECT = _socket.socket.connect


@pytest.fixture(autouse=True)
def no_outbound_network(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[None]:
    """Make a real HTTP request from a test an error, not a surprise.

    This is not paranoia. `test_the_400_that_the_user_saw_is_gone` posted a
    well-formed body to the live provider on every suite run: conftest scrubs the
    API key, so it cost one real request per run and got a 401 back, and the
    request count was only noticed by counting `llm.request` lines in
    logs/llm.log by hand.

    Loopback is allowed through: `TestClient` drives the app in-process but the
    event loop and the ASGI portal still touch 127.0.0.1, and blocking that broke
    every route test. A provider call never goes to loopback, so nothing real is
    let past.

    The live tests opt back in with `@pytest.mark.live`. Everything else is
    expected to fake the client, and this makes that expectation enforceable
    rather than a convention.
    """
    if request.node.get_closest_marker("live"):
        yield
        return

    import ipaddress
    import socket

    def _is_loopback(address: object) -> bool:
        host = address[0] if isinstance(address, tuple) else address
        if not isinstance(host, str):
            return False
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return host in ("localhost", "localhost.localdomain")

    def blocked(self, address, *args, **kwargs):  # type: ignore[no-untyped-def]
        if _is_loopback(address):
            return _REAL_CONNECT(self, address, *args, **kwargs)
        host = address[0] if isinstance(address, tuple) else address
        raise AssertionError(
            f"a test opened a real connection to {host!r}. Fake the httpx "
            "client, or mark the test @pytest.mark.live and set RUN_LIVE_LLM."
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    try:
        yield
    finally:
        monkeypatch.undo()


@pytest.fixture(autouse=True)
def temp_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Give every test its own DB file and log dir."""
    db_path = "test_resume.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("LOG_DIR", "logs")
    config.get_settings.cache_clear()
    db.init_db()
    yield db_path
    config.get_settings.cache_clear()
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db_path + suffix)
        except OSError:
            pass


@pytest.fixture
def sample_profile_payload() -> dict:
    return Profile.model_validate(
        {
            "contact": {
                "name": "Anon",
                "email": "anon@example.com",
                "phone": "+91 98765 43210",
                "city": "Bengaluru",
                "country": "India",
                "links": [
                    {"label": "GitHub", "url": "https://example.org"},
                    {"label": "LinkedIn", "url": "https://example.org"},
                ],
            },
            "summary": (
                "Backend engineer with 3 years building payment and staffing "
                "services in Python. Reduced p99 checkout latency and owned a "
                "Postgres migration with zero customer-visible downtime."
            ),
            "education": [
                {
                    "institution": "BITS Pilani",
                    "degree": "B.E.",
                    "field": "Computer Science",
                    "start": "2019-08",
                    "end": "2022-06",
                    "grade": {"value": "8.7", "scale": "10"},
                    "coursework": ["Distributed Systems", "Databases"],
                }
            ],
            "experience": [
                {
                    "org": "PayFlow",
                    "role": "Backend Engineer",
                    "type": "job",
                    "location": "Bengaluru",
                    "start": "2022-07",
                    "end": "Present",
                    "bullets": [
                        {
                            "raw_facts": "cut p99 checkout latency from 900ms to 240ms",
                            "text": "Cut p99 checkout latency from 900ms to 240ms by adding Redis read-through caching on the cart and payment-intent paths.",
                            "metrics": ["900ms -> 240ms"],
                            "tags": ["latency"],
                            "tools": ["Redis", "Python"],
                        },
                        {
                            "raw_facts": "migrated Postgres 11 to 15 with no downtime",
                            "text": "Migrated Postgres 11 to 15 across 4 services using logical replication, with zero customer-visible downtime.",
                            "metrics": ["4 services", "zero downtime"],
                            "tags": ["migration"],
                            "tools": ["Postgres", "PostgreSQL"],
                        },
                    ],
                }
            ],
            "projects": [
                {
                    "name": "Staffing Scheduler",
                    "role": "Solo build",
                    "links": [{"label": "GitHub", "url": "https://example.org/scheduler"}],
                    "start": "2021-01",
                    "end": "2021-06",
                    "tech": ["FastAPI", "Postgres", "Celery"],
                    "bullets": [
                        {
                            "raw_facts": "built shift scheduler used by 12 stores",
                            "text": "Built a FastAPI and Postgres shift scheduler now used by 12 stores to publish weekly rosters in under 30 seconds.",
                            "metrics": ["12 stores", "under 30s"],
                            "tags": [],
                            "tools": ["FastAPI", "Postgres", "Celery"],
                        }
                    ],
                }
            ],
            "skills": [
                {"name": "Languages", "items": ["Python", "SQL", "Go"]},
                {"name": "Backend", "items": ["FastAPI", "Django", "Celery"]},
                {"name": "Data", "items": ["Postgres", "Redis", "Kafka"]},
            ],
            "certifications": [
                {
                    "name": "AWS Certified Solutions Architect - Associate",
                    "issuer": "Amazon Web Services",
                    "date": "2024-03",
                }
            ],
            "achievements": [
                {"name": "Winner, BITS Hackathon 2021", "date": "2021-11"}
            ],
            "personal_details": {},
        }
    ).model_dump(mode="json")
