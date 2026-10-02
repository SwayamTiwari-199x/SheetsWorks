"""Shared fixtures: isolated temp DB per test, and a fake httpx client."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Point at a throwaway DB before app.config is imported anywhere.
os.environ["DATABASE_URL"] = "sqlite:///./test_resume.db"
os.environ["LOG_DIR"] = "logs"
for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY"):
    os.environ.pop(var, None)

from app import config, db  # noqa: E402
from app.models import Profile  # noqa: E402


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
def settings_factory():
    """Build Settings with an explicit provider, bypassing the .env file."""

    def _make(provider: str, **overrides):
        return config.Settings(
            llm_provider=provider,
            _env_file=None,
            **{k: v for k, v in overrides.items() if k != "api_key"},
        )

    return _make


@pytest.fixture
def sample_profile_payload() -> dict:
    return Profile.model_validate(
        {
            "contact": {
                "name": "Aditi Sharma",
                "email": "aditi.sharma@example.com",
                "phone": "+91 98765 43210",
                "city": "Bengaluru",
                "country": "India",
                "links": [
                    {"label": "GitHub", "url": "https://github.com/aditi"},
                    {"label": "LinkedIn", "url": "https://linkedin.com/in/aditi"},
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
                    "links": [{"label": "GitHub", "url": "https://github.com/aditi/scheduler"}],
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
