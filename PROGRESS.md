# PROGRESS

CURRENT STAGE: 3 (Frontend: profile editor)

## Done
- Stage 0 (accepted): `RULES.md` + `rules.json`, 75 distinct source URLs across 56 domains, every rule `verified`/`unverified`, `rules.json` parses. Repairs: `ats.layout_rules[5]` was still truncated after `8644a84` (valid JSON, garbled text) — fixed in `2f21233`; `meta.source_count` verified at 75 with a reproducible counting command in the RULES.md header; market-snapshot staleness made machine-checkable.
- Stage 1 (accepted): FastAPI app, pydantic models for Profile/Version/JobDescription/Application (SPEC §4), SQLite storage, `GET/PUT /profile`, provider-agnostic `llm.py`, `--check-llm`.
- Stage 2 (accepted): renderers profile/version JSON → ATS-safe PDF (WeasyPrint), DOCX (python-docx), TXT. Canonical `Doc` intermediate means DOCX and TXT are textually identical by construction. `app/rules.py` is the single loader for every convention. `POST /versions/from-profile` + `POST /export/{version_id}?format=pdf|docx|txt`. **180 tests pass.**

### Stage 2 findings and fixes
- **Silent data loss (the important one).** `rules.json`'s `experienced` section order omitted `achievements_awards`, and `build_doc` iterated that list exactly — so an experienced candidate's Achievements section vanished from all three formats with no error and no warning. Fixed at the root: `achievements_awards` added to both level orders, plus a machine-readable `section_order.fallback_append` rule stating that a populated section the order did not place is appended, never discarded. RULES.md §3 amended with the gap and an honest `unverified` tag on the placement.
- **A heading was hardcoded in Python.** `"Publications"` bypassed `rules.json`, which CLAUDE.md forbids. Now read via `rules.heading()`, and `Publications` added to `safe_headings.acceptable` with a note that it comes from SPEC §3 rather than a cited source.
- **Page budget was ignored.** A heavy fresher CV rendered on 2 pages against a 1-page `rules.json` limit. The renderer now scales density (`normal` 1.0in → `compact` 0.75in → `tight` 0.5in) until it fits. Font is never scaled below the researched 10.5pt minimum and margins never below the researched 0.5in minimum. Measured: 12 bullets go 2 pages → 1 page via compression. If even `tight` overflows, the export returns a valid PDF but sets `X-Page-Budget: over` and logs a warning — trimming content is Stage 6's job.
- **`market_snapshot.stale_after` disagreed with `stale_after_days`** (2027-01-02 is 92 days, not 90) and staleness used `>` so the expiry date itself counted as fresh. Corrected to 2026-12-31 with `>=`; a test now keeps the two fields in step.
- Removed out-of-scope routes `/versions`, `/jd`, `/applications` (Stage 6/8) and `POST /validate/{version_id}` (Stage 7) — the last returned `passed: true` unconditionally. The *models* stay because Stage 1 asked for them per SPEC §4. The `versions` **table** came back, but only because Stage 2's required `POST /export/{version_id}` is dead code without it; listing/tailoring/JD links remain absent.
- **Security pass** (21 tests in `tests/test_security.py`): DNS rebinding closed with `TrustedHostMiddleware`; over-nested JSON (~6KB of `[`) caused a 500 + traceback, now 422; invisible/control characters (NUL, U+202E RTL override, zero-width, bidi isolates, BOM, DEL) rejected naming the code point; list fields capped at 60/12/20. Verified **not** vulnerable with tests: SQL injection (queries are parameterised), CORS absent by design, no secret in any response.
- Earlier fixes: `put_profile` keyed rows on the auto-generated `Profile.id` instead of `default`; test suite was not hermetic (`_env_file=None` does not disable process-env reads in pydantic-settings 2.15); `gemini-2.5-flash` retired for new accounts → `gemini-3.8-flash`; `--check-llm` gave raw tracebacks, now status-specific hints.

## Commands
- install: `python -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt`
- tests: `.venv\Scripts\python -m pytest`
- app: `.venv\Scripts\python -m uvicorn app.main:app --reload` (http://localhost:8000, docs at /docs)
- export: `POST /versions/from-profile?name=My Resume`, then `POST /export/<id>?format=pdf|docx|txt`
- check LLM: `.venv\Scripts\python -m app.cli --check-llm` (exit 0 pass / 1 fail; needs a real key in `.env`)

## Notes / decisions
- One stage at a time (CLAUDE.md rule 2): no speculative endpoints or helpers for later stages. `test_stage2_exposes_only_its_own_routes` and `test_later_stage_routes_are_absent` fail if they creep back.
- rules.json is a summary of RULES.md; RULES.md is prose-of-truth with sources. `app/rules.py` is the only reader, so no convention is ever taken from model memory.
- **PDF engine: WeasyPrint, decided on measurement.** On a realistic fresher CV, Tectonic + Calibri dropped *every word space* in text extraction (`BITS Pilani` → `BITSPilani`, `+91 98765 43210` → `+919876543210`), keeping 9/20 content canaries; WeasyPrint kept 19/19, extracted with Calibri intact, and rendered in ~260ms vs ~4.7s. A PDF that looks right but cannot be text-parsed defeats the purpose of an ATS-targeted tool. Tectonic + Arial extracts correctly and remains a fallback if a future stage needs LaTeX.
- **Bullets are a literal ASCII hyphen**, not a CSS list marker: a generated `•` or `–` extracts as U+FFFD, garbling ATS text. Confirmed empirically and enforced by `test_criterion2_no_garbled_glyphs`. This implements RULES.md §2's "decorative bullet glyphs can garble".
- Section headings render uppercase (industry convention); the underlying strings stay title-case per `safe_headings`. ATS heading matching is case-insensitive.
- Personal details are opt-in per version and off by default. They are read as text only; `photo_path` is never opened.
- HTML and `photo_path` are stored verbatim on purpose. **Stage 3 must assign profile fields with `textContent`, never `innerHTML`.** JD text will be third-party input in Stage 5 and is the realistic XSS vector.
- `llm.py`: `ask(schema, prompt)` only. gemini/groq/mistral share one OpenAI-compatible httpx path; anthropic has its own `/messages` branch. Schema embedded in the prompt, no provider JSON modes. Retry exactly once, then `LLMError`. HTTP failures also become `LLMError` with a status hint.
- Tests fake `httpx.Client` (tests/fakes.py) rather than using `respx`: one fewer dependency, and it asserts the *number* of HTTP calls, which is the retry-once contract.
- Dates are ISO strings validated by regex, not `date` types, so `2022-07` is valid without inventing day numbers. `end="Present"` allowed; `end < start` rejected. Rendered as `Jul 2022`, never `'22`.

## Known issues
- **BLOCKER for live LLM use:** the configured Gemini project returns 403 "Your project has been denied access" for all Gemini 3.x models, and the 2.5 family is retired for new accounts. Enable model access in Google AI Studio / Cloud console, or point `LLM_PROVIDER` at another provider. All code paths are proven by mocks; only the live wire format is unverified. Stages 4+ depend on this.
- A resume genuinely longer than the page budget (16+ long bullets on one page) still exports at 2 pages with `X-Page-Budget: over`. Intentional — Stage 6 does deliberate trimming.
- Python 3.14 in use; starlette warns `httpx` with `TestClient` is deprecated in favour of `httpx2`. Harmless now.
- Stage 3 has no UI yet: the app serves JSON only.
