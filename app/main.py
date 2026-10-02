"""FastAPI app: /docs, health, GET/PUT /profile, and the in-memory placeholders
for Version / JobDescription / Application so later stages have real routes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from . import db
from .models import (
    Application,
    JobDescription,
    Profile,
    ValidationReport,
    Version,
)

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


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# Versions (render/tailor arrive in later stages; storage only here)
# --------------------------------------------------------------------------


@app.get("/versions", response_model=list[Version])
def list_versions() -> list[Version]:
    return [Version.model_validate(v) for v in db.list_versions()]


@app.post("/versions", response_model=Version, status_code=201)
def create_version(version: Version) -> Version:
    return Version.model_validate(db.put_version(version.model_dump(mode="json")))


# --------------------------------------------------------------------------
# Job descriptions
# --------------------------------------------------------------------------


@app.post("/jd", response_model=JobDescription, status_code=201)
def create_jd(jd: JobDescription) -> JobDescription:
    return JobDescription.model_validate(db.put_job_description(jd.model_dump(mode="json")))


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------


@app.get("/applications", response_model=list[Application])
def list_applications() -> list[Application]:
    return [Application.model_validate(a) for a in db.list_applications()]


@app.post("/applications", response_model=Application, status_code=201)
def create_application(app_entry: Application) -> Application:
    return Application.model_validate(db.put_application(app_entry.model_dump(mode="json")))


# --------------------------------------------------------------------------
# Validation placeholder (real validators are Stage 7)
# --------------------------------------------------------------------------


@app.post("/validate/{version_id}", response_model=ValidationReport)
def validate_placeholder(version_id: str) -> ValidationReport:
    if db.get_version(version_id) is None:
        raise HTTPException(status_code=404, detail=f"version {version_id} not found")
    return ValidationReport(
        passed=True, errors=[], warnings=["Stage 1 placeholder: real validators land in Stage 7"]
    )
