"""FastAPI app.

Stage 1 scope only: `/docs`, a health check, and `GET/PUT /profile`.

Deliberately absent: `/versions`, `/jd`, `/applications` (Stage 6/8) and
`/validate/{version_id}` (Stage 7). They are re-added by the stage that
actually needs them rather than stubbed here — a validator endpoint that
returns `passed: true` unconditionally is worse than no endpoint at all.
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import db, rules
from .models import Profile, Version
from .render import (
    MEDIA_TYPES,
    RENDERERS,
    build_doc_from_version,
    render_pdf_report,
)

logger = logging.getLogger("app.main")

PROFILE_ID = "default"

# This app has no auth (SPEC section 10) and is meant for localhost only. Without
# a Host check, a malicious web page could point a DNS record at 127.0.0.1 and
# talk to the app from the browser -- DNS rebinding. CORS does not help: a simple
# GET carries no preflight, and the browser blocks the *read*, not the request.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]

# Resume fields are length-capped, but a deeply nested JSON body is not a length
# problem: ~6KB of "[" trips Python's recursion limit inside pydantic's error
# reporting, which raises RecursionError and surfaces as a 500 with a traceback.
# Catch it and answer like any other bad request.
RECURSION_MESSAGE = (
    "request body is nested too deeply to validate; "
    "send a normal JSON object instead"
)


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

app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def catch_recursion_errors(request, call_next):
    """Turn a RecursionError from an over-nested body into a 422, not a 500."""
    try:
        return await call_next(request)
    except RecursionError:
        logger.warning("rejected over-nested body on %s", request.url.path)
        return JSONResponse(status_code=422, content={"detail": RECURSION_MESSAGE})


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


# --------------------------------------------------------------------------
# Versions and export (Stage 2)
# --------------------------------------------------------------------------

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@app.post("/versions", response_model=Version, status_code=201)
def create_version(version: Version) -> Version:
    """Snapshot the current profile (or an explicit snapshot) as a version.

    Stage 2 needs exactly one stored document so POST /export/{version_id} has
    something to export. Tailoring and JD linking are Stage 6.
    """
    return Version.model_validate(db.put_version(version.model_dump(mode="json")))


@app.post("/versions/from-profile", response_model=Version, status_code=201)
def snapshot_current_profile(name: str = "current", include_personal_details: bool = False) -> Version:
    """Convenience: snapshot whatever is in /profile right now."""
    stored = db.get_profile(PROFILE_ID)
    if stored is None:
        raise HTTPException(status_code=404, detail="no profile yet; PUT /profile first")
    version = Version(
        name=name,
        profile_snapshot=Profile.model_validate(stored),
        include_personal_details=include_personal_details,
    )
    return Version.model_validate(db.put_version(version.model_dump(mode="json")))


@app.post("/export/{version_id}")
def export_version(
    version_id: str,
    format: str = "pdf",
    download: bool = True,
) -> Response:
    """Render a stored version to PDF, DOCX or TXT.

    Returns the page count for PDFs in an X-Pages header so the page budget
    from rules.json can be checked without re-parsing the file.
    """
    fmt = format.lower()
    if fmt not in RENDERERS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported format {format!r}; use one of {sorted(RENDERERS)}",
        )

    stored = db.get_version(version_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"version {version_id} not found")
    version = Version.model_validate(stored)
    doc = build_doc_from_version(version)

    limit = rules.page_limit(doc.level)
    headers = {"X-Page-Limit": str(limit)}
    if fmt == "pdf":
        payload, pages, density = render_pdf_report(doc, max_pages=limit)
        headers["X-Pages"] = str(pages)
        headers["X-Density"] = density
        over = pages > limit
        headers["X-Page-Budget"] = "over" if over else "ok"
        if over:
            # Honest rather than silent: the layout already squeezed as far as
            # rules.json allows, so content has to be trimmed (Stage 6's job).
            logger.warning(
                "version %s renders on %d pages, over the %d-page budget for a "
                "%s resume; content must be trimmed",
                version_id, pages, limit, doc.level,
            )
    else:
        payload = RENDERERS[fmt](doc)

    filename = f"{_SAFE_NAME.sub('_', version.name or version_id)}.{fmt}"
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(
        content=payload,
        media_type=MEDIA_TYPES[fmt],
        headers=headers,
    )
