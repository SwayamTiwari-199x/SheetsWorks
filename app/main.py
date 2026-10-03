"""FastAPI app.

Stage 1: `/docs`, `/health`, `GET/PUT /profile`.
Stage 2: `POST /versions`, `POST /versions/from-profile`, `POST /export/{version_id}`.

Deliberately absent: `/assist/*` (Stage 4), `/jd/*` (Stage 5), `/tailor`
(Stage 6), `/validate/{version_id}` (Stage 7) and `/applications` (Stage 8).
They are re-added by the stage that actually needs them rather than stubbed
here — a validator endpoint that returns `passed: true` unconditionally is
worse than no endpoint at all.
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import db, rules
from .models import Profile, Version
from .render import (
    MEDIA_TYPES,
    RENDERERS,
    build_doc,
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

# Two policies, not one. API responses are data and must never be treated as a
# document; the terminal page does need to load its own stylesheet and script.
API_CSP = "default-src 'none'; frame-ancestors 'none'"
# blob: is required in frame-src: the live preview is rendered to a blob URL in
# the browser and shown in an iframe. CSP 'self' matches by scheme+host+port, so
# a blob: frame is blocked without it -- which failed silently as a blank pane.
PAGE_CSP = (
    "default-src 'self'; style-src 'self'; script-src 'self'; "
    "img-src 'self' data:; frame-src 'self' blob:; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

COMMON_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}

# Resume fields are length-capped, but a deeply nested JSON body is not a length
# problem: ~6KB of "[" trips Python's recursion limit inside pydantic's error
# reporting, which raises RecursionError and surfaces as a 500 with a traceback.
# Catch it and answer like any other bad request.
RECURSION_MESSAGE = (
    "request body is nested too deeply to validate; "
    "send a normal JSON object instead"
)

# Request paths are attacker-controlled and %0A decodes to a newline, so an
# unsanitised path in a log line would let a caller forge log entries.
_LOG_UNSAFE = re.compile(r"[^\x20-\x7e]")


def _log_safe(value: str) -> str:
    return _LOG_UNSAFE.sub("?", value)[:200]


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
async def security_and_recursion(request, call_next):
    """Attach hardening headers and turn an over-nested body into a 422."""
    try:
        response = await call_next(request)
    except RecursionError:
        logger.warning(
            "rejected over-nested body on %s", _log_safe(request.url.path)
        )
        response = JSONResponse(status_code=422, content={"detail": RECURSION_MESSAGE})

    path = request.url.path
    is_page = path in ("/", "") or path.startswith("/static/")
    response.headers["Content-Security-Policy"] = PAGE_CSP if is_page else API_CSP
    for key, value in COMMON_SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


@app.get("/", include_in_schema=False)
def terminal_page() -> FileResponse:
    """The single-page terminal UI (Stage 3)."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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

# Filename sanitiser. Spaces are deliberately ALLOWED: the sheets convention is
# "FirstName LastName Resume", so stripping them would defeat the very rule we
# are implementing. Everything that could break out of the quoted
# Content-Disposition header is removed instead.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9 ._-]+")
_MULTI_SPACE = re.compile(r"\s+")


def _clean_filename(value: str) -> str:
    cleaned = _MULTI_SPACE.sub(" ", _SAFE_NAME.sub("_", value)).strip(" ._-")
    return cleaned or "resume"


@app.post("/versions", response_model=Version, status_code=201)
def create_version(version: Version) -> Version:
    """Snapshot the current profile (or an explicit snapshot) as a version.

    Stage 2 needs exactly one stored document so POST /export/{version_id} has
    something to export. Tailoring and JD linking are Stage 6.
    """
    return Version.model_validate(db.put_version(version.model_dump(mode="json")))


@app.post("/versions/from-profile", response_model=Version, status_code=201)
def snapshot_current_profile(
    name: str = "current",
    include_personal_details: bool = False,
    template: str = Query("blank", description="resume template name"),
) -> Version:
    """Convenience: snapshot whatever is in /profile right now."""
    stored = db.get_profile(PROFILE_ID)
    if stored is None:
        raise HTTPException(status_code=404, detail="no profile yet; PUT /profile first")
    version = Version(
        name=name,
        profile_snapshot=Profile.model_validate(stored),
        include_personal_details=include_personal_details,
        template=template,
    )
    return Version.model_validate(db.put_version(version.model_dump(mode="json")))


@app.post("/export/{version_id}")
def export_version(
    version_id: str,
    fmt: str = Query("pdf", alias="format", description="pdf | docx | txt"),
) -> Response:
    """Render a stored version to PDF, DOCX or TXT.

    PDFs report the page count and budget in headers, so the rules.json page
    limit can be checked without re-parsing the file. Exports are personal
    documents, so they are sent no-store.
    """
    fmt = fmt.lower()
    if fmt not in RENDERERS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported format {fmt!r}; use one of {sorted(RENDERERS)}",
        )

    stored = db.get_version(version_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"version {version_id} not found")
    version = Version.model_validate(stored)
    doc = build_doc_from_version(version)

    limit = _page_limit_for(doc, version.template)
    headers = {
        "X-Page-Limit": str(limit),
        "X-Template": rules.template(version.template).get("label", version.template).split(" -")[0],
        "Cache-Control": "no-store",
    }
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
                _log_safe(version_id), pages, limit, doc.level,
            )
    else:
        payload = RENDERERS[fmt](doc)

    stem = _export_filename(version, fmt)
    headers["Content-Disposition"] = f'attachment; filename="{stem}.{fmt}"'
    return Response(
        content=payload,
        media_type=MEDIA_TYPES[fmt],
        headers=headers,
    )


# --------------------------------------------------------------------------
# Live preview (Stage 3)
# --------------------------------------------------------------------------


@app.post("/preview")
def preview_current_profile(
    profile: Profile,
    template: str = Query("blank", description="resume template name"),
) -> Response:
    """Render the profile the caller just sent, without storing a version.

    Deliberately takes the body rather than reading /profile: the terminal
    autosaves on a debounce, and a preview that waited for the save would lag
    behind the keystrokes. This is the same renderer the exporter uses, so the
    preview is the real artifact and not an HTML approximation that could
    quietly disagree with the exported file.
    """
    doc = build_doc(profile, template=template)
    limit = _page_limit_for(doc, template)
    payload, pages, density = render_pdf_report(doc, max_pages=limit)
    return Response(
        content=payload,
        media_type=MEDIA_TYPES["pdf"],
        headers={
            "X-Pages": str(pages),
            "X-Page-Limit": str(limit),
            "X-Page-Budget": "over" if pages > limit else "ok",
            "X-Density": density,
            "X-Level": doc.level,
            "X-Template": template,
            "Cache-Control": "no-store",
            "Content-Disposition": "inline",
        },
    )


def _page_limit_for(doc, template: str) -> int:
    """Page budget for this resume.

    A template may be stricter than the researched default -- the sheets
    template demands one page even for experienced candidates, per its source.
    """
    spec = rules.template(template)
    return int(spec.get("max_pages") or rules.page_limit(doc.level))


def _export_filename(version, fmt: str) -> str:
    """Filename per the active template's convention.

    The sheets source is emphatic that this must be "FirstName LastName Resume"
    and never "(Project Management)", "Final" or a year, so that is data in
    rules.json rather than a name built here.
    """
    spec = rules.template(version.template)
    pattern = spec.get("filename_pattern") or "{name}"
    parts = [p for p in str(version.name or "").split() if p]
    if not parts:
        full = "resume"
    elif len(parts) == 1:
        full = parts[0]
    else:
        full = f"{parts[0]} {parts[-1]}"
    rendered = pattern.replace("{name}", full)
    return _clean_filename(rendered)
