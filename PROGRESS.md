# PROGRESS

CURRENT STAGE: 2 (Renderers, no AI yet)

## Done
- Stage 0 (accepted): `RULES.md` + `rules.json`, 75 distinct source URLs across 56 domains, every rule `verified`/`unverified`, `rules.json` parses. Repairs: `ats.layout_rules[5]` was still truncated after `8644a84` (valid JSON, garbled text) — fixed in `2f21233`; `meta.source_count` verified at 75 with a reproducible counting command in the RULES.md header; market-snapshot staleness made machine-checkable (`stale_after: 2027-01-02`, `stale_after_days: 90`).
- Stage 1 (accepted): FastAPI app, pydantic models for Profile/Version/JobDescription/Application (SPEC §4), SQLite storage, `GET/PUT /profile`, provider-agnostic `llm.py`, `--check-llm`. 80 pytest tests, all mocked, no real key needed.

### Fixes applied to Stage 0/1 after acceptance
- `put_profile` keyed rows on the auto-generated `Profile.id` instead of the singleton `default` key, so `GET /profile` 404'd after a successful PUT.
- Test suite was not hermetic: `_env_file=None` does **not** disable process-env reads in pydantic-settings 2.15, so a stray `LLM_PROVIDER` broke the suite on one machine only. Added autouse `isolated_llm_env` fixture + regression tests.
- `gemini-2.5-flash` is retired for new accounts (404). Default moved to `gemini-3.8-flash`.
- `--check-llm` dumped raw httpx tracebacks; HTTP failures now become `LLMError` with status-specific hints. Credentials never enter an error message or `logs/llm.log` (verified).
- **Removed out-of-scope routes:** `/versions`, `/jd`, `/applications` (Stage 6/8) and `POST /validate/{version_id}` (Stage 7) — the last returned `passed: true` unconditionally, which would have let Stage 3 wire an export button to a validator that always approves. Their db tables and accessors are gone too. The *models* remain, because Stage 1 explicitly asked for them per SPEC §4.
- **Removed dead code:** `ConfigError` (defined, exported, never raised), unused `pydantic.Field` import in `config.py`, `_rows_to_models` in `db.py`, unreachable duplicate branch in `_extract_error_message`, and a UTF-8 BOM that a PowerShell edit had introduced into `db.py`.
- `test_stage1_exposes_only_its_own_routes` now fails if speculative endpoints creep back.
- **Security pass** (adversarial probe of the live API, all findings fixed + pinned by `tests/test_security.py`, 21 tests):
  - DNS rebinding: any `Host` header was accepted. Now `TrustedHostMiddleware` allows only localhost/127.0.0.1/[::1]. CORS alone would not help — a simple GET carries no preflight and the browser blocks the read, not the request.
  - Over-nested JSON (~6KB of `[`) crashed pydantic's error reporting with `RecursionError`, surfacing as **500 + stack trace**. Now caught and answered 422.
  - Invisible/control characters were stored verbatim: NUL, U+202E RTL override (visually reverses text), zero-width and bidi isolates, BOM, DEL. Rejected with a named code point. Tab/newline still allowed, and accents/Devanagari unaffected.
  - List fields were unbounded (500 achievements accepted). Capped: 60 entries per list, 12 bullets, 20 links.
  - Confirmed **not** vulnerable, with tests: SQL injection (all payloads stored inert; queries are parameterised), CORS absent by design, no secret in any API response. HTML and `photo_path` are stored verbatim on purpose — the data is the user's own; Stage 3 must use `textContent`, never `innerHTML`, and a renderer must never open `photo_path`.

## Commands
- install: `python -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt`
- tests: `.venv\Scripts\python -m pytest`
- app: `.venv\Scripts\python -m uvicorn app.main:app --reload` (http://localhost:8000, docs at /docs)
- check LLM: `.venv\Scripts\python -m app.cli --check-llm` (exit 0 pass / 1 fail; needs a real key in `.env`)
- list providers: `.venv\Scripts\python -m app.cli --list-providers`

## Notes / decisions
- rules.json is a summary of RULES.md; RULES.md is prose-of-truth with sources. App code reads rules.json.
- One stage at a time (CLAUDE.md rule 2): no speculative endpoints or helpers for later stages. Re-added by the stage that needs them.
- REC: treat photo/DOB/gender/marital/father's-name as omit-by-default (even in India) — legacy biodata fields noted but not endorsed.
- AI-detection stance per SPEC §2/§10: no detector-evasion features; defense is user's own facts + human review.
- Market snapshot collected 2026-10-02, expires **2027-01-02**. Check `market_snapshot.stale_after` before showing those figures.
- `llm.py`: `ask(schema, prompt)` only. gemini/groq/mistral share one OpenAI-compatible httpx path; anthropic has its own `/messages` branch. Schema is embedded in the prompt — no provider JSON modes anywhere. Retry exactly once, then `LLMError`. HTTP failures also become `LLMError` with a status hint (401/403/404/429) plus `report()` for the CLI.
- Tests fake `httpx.Client` (tests/fakes.py) rather than using `respx`: one less dependency, and it asserts the *number* of HTTP calls, which is the retry-once contract. The fake wraps a real `httpx.Response` so `raise_for_status()` behaves like the real client.
- Dates are ISO strings validated by regex, not `date` types, so `2022-07` (month precision) is valid without inventing day numbers. `end="Present"` allowed; `end < start` rejected.
- `Profile` is a singleton stored under row key `default`.
- **PDF engine decision (Stage 2):** tested WeasyPrint vs Tectonic. Tectonic + Calibri silently drops **every word space** in text extraction (`BITS Pilani` → `BITSPilani`, `+91 98765 43210` → `+919876543210`), which would defeat ATS keyword matching. Tectonic + Arial extracts correctly. WeasyPrint extracts correctly with any safe font. Recommendation: WeasyPrint default, Tectonic optional.

## Known issues
- **BLOCKER for live LLM use:** the configured Gemini project returns 403 "Your project has been denied access" for all Gemini 3.x models, and the 2.5 family is retired for new accounts. Enable model access in Google AI Studio / Cloud console, or point `LLM_PROVIDER` at another provider. All code paths are proven by mocks; only the live wire format is unverified.
- Python 3.14 in use; starlette warns `httpx` with `TestClient` is deprecated in favour of `httpx2`. Harmless now.
- Stage 2 needs a Tectonic-vs-WeasyPrint decision and, if both ship, a `PDF_ENGINE` setting.
