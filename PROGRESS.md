# PROGRESS

CURRENT STAGE: 2 (Renderers, no AI yet)

## Done
- Stage 0 (accepted): `RULES.md` + `rules.json` written (75 distinct source URLs cited; rules.json parses). Post-acceptance fixes: SPEC.md has per-version `include_personal_details` toggle (default off) plus verified-blocks/unverified-warns validator rule; `rules.json` bullet min 15 aligned with RULES.md §4; §0 detector line reworded to "rarely, per limited evidence"; `meta.source_count` corrected 30 → 75. `ats.layout_rules[5]` was still truncated after commit 8644a84 (valid JSON, garbled text) — repaired in `2f21233`.
- Stage 1 (accepted): FastAPI app + pydantic models (SPEC §4) + SQLite storage + `GET/PUT /profile` + provider-agnostic `llm.py` + `--check-llm`. 72 pytest tests, all passing, no real key needed. Bug found and fixed during acceptance: `put_profile` keyed rows on the auto-generated `Profile.id` instead of the singleton `default` key, so `GET /profile` 404'd after a successful PUT.

## Commands
- install: `python -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt`
- tests: `.venv\Scripts\python -m pytest`
- app: `.venv\Scripts\python -m uvicorn app.main:app --reload` (http://localhost:8000, docs at /docs)
- check LLM: `.venv\Scripts\python -m app.cli --check-llm` (exit 0 pass / 1 fail; needs a real key, set in `.env`)
- list providers: `.venv\Scripts\python -m app.cli --list-providers`

## Notes / decisions
- rules.json is a summary of RULES.md; RULES.md is prose-of-truth with sources. App code reads rules.json.
- REC: treat photo/DOB/gender/marital/father's-name as omit-by-default (even in India) — legacy biodata fields noted but not endorsed.
- AI-detection stance per SPEC §2/§10: no detector-evasion features; defense is user's own facts + human review (TopResume 2025 survey: 19.6% reject AI resumes outright).
- Market snapshot dated 2026-10-02 — needs `refresh_market_data` every ~3 months.
- LLM: `ask(schema, prompt)` only. gemini/groq/mistral share one OpenAI-compatible httpx path; anthropic has its own `/messages` branch. Schema is embedded in the prompt — no provider JSON modes anywhere. Retry exactly once, then `LLMError`. HTTP failures are also translated into `LLMError` carrying a status-specific hint (401 bad key / 403 no project access / 404 retired model / 429 quota) plus `report()` for the CLI. Credentials never appear in an error message or in `logs/llm.log` (verified).
- Tests fake `httpx.Client` (tests/fakes.py) instead of using `respx`: one less dependency, and it lets us assert the *number* of HTTP calls, which is the retry-once contract. The fake wraps a real `httpx.Response` so `raise_for_status()` behaves exactly like the real thing.
- **Test hermeticity:** `conftest.py` has an autouse `isolated_llm_env` fixture scrubbing `LLM_*` and `*_API_KEY` from the process env. `_env_file=None` does NOT disable process-env reads in pydantic-settings 2.15, so without this the suite read the developer's real `.env`/shell vars and failed on one machine but passed on another.
- Verified against the real Gemini API: `gemini-2.5-flash` / `2.5-pro` / `2.5-flash-lite` are **retired for new accounts** (404 "no longer available to new users"). Default moved to `gemini-3.8-flash`. Gemini 3.x currently answers **403 "Your project has been denied access"** on this account — an account/project permission issue, not a code defect.
- Dates are ISO strings validated by regex, not `date` types, so `2022-07` (month precision) is valid without inventing day numbers. `end="Present"` allowed; `end < start` rejected.
- `Profile` is a singleton stored under row key `default`; versions/JDs/applications are normal keyed rows.

## Known issues
- **BLOCKER for live LLM use:** the configured Gemini project returns 403 "Your project has been denied access" for all Gemini 3.x models, and the 2.5 family is retired for new accounts. Need the user to enable model access in Google AI Studio / Cloud console, or point `LLM_PROVIDER` at another provider. All code paths are proven by mocks; only the live wire format is unverified.
- Python 3.14 in use; starlette warns that `httpx` with `TestClient` is deprecated in favour of `httpx2`. Harmless now; revisit if starlette drops `httpx` support.
- Stage 2 still needs a decision: Tectonic (LaTeX) vs WeasyPrint for PDF.
