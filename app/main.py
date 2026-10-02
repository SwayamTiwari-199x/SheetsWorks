"""FastAPI app.

Stage 1 scope only: `/docs`, a health check, and `GET/PUT /profile`.

Deliberately absent: `/versions`, `/jd`, `/applications` (Stage 6/8) and
`/validate/{version_id}` (Stage 7). They are re-added by the stage that
actually needs them rather than stubbed here — a validator endpoint that
returns `passed: true` unconditionally is worse than no endpoint at all.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from . import db
from .models import Profile

PROFILE_ID = "default"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="Personal AI Resume Builder",
    version="1.0.0",
    description=(
        "Local resume builder. Profile is stored as a JSON document; renderers "
        "and AI assist come in later stages."
    ),
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/profile", response_model=Profile)
def get_profile() -> Profile:
    data = db.get_profile(PROFILE_ID)
    if data is None:
        raise HTTPException(status_code=404, detail="no profile yet; PUT /profile first")
    return Profile.model_validate(data)


@app.put("/profile", response_model=Profile)
def put_profile(profile: Profile) -> Profile:
    """Full replace. The response is the stored profile, so it round-trips."""
    data = db.put_profile(profile.model_dump(mode="json"), PROFILE_ID)
    return Profile.model_validate(data)
