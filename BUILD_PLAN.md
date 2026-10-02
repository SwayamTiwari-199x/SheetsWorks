# BUILD_PLAN — one stage at a time

How to use: paste the **Prompt** of the CURRENT stage into the coding agent (start a fresh session per stage; the agent reads CLAUDE.md, SPEC.md, PROGRESS.md automatically). Agent plans first, I approve, it builds, runs the **Acceptance tests**, commits, updates PROGRESS.md.

Order rationale: research and schema come first because everything depends on them. The frontend comes after the backend has something real to talk to.

---

## Stage 0 — Research → RULES.md
**Prompt:** "Do Stage 0 from BUILD_PLAN.md. Use web search to research everything in SPEC.md section 9 and write `RULES.md`. Every rule needs a source URL, a date, and a `verified`/`unverified` tag. Separate Global and India sections. End with a machine-readable block `rules.json` containing: max_pages by level, section order by level (student/fresher, experienced), safe section headings, banned phrases list, preferred verbs list, bullet count and length limits, India-specific field guidance. No app code in this stage."
**Acceptance:**
- `RULES.md` and `rules.json` exist; `rules.json` parses.
- At least 15 distinct sources; no rule without a source.
- Includes the honest section on AI-detection and recruiter attitude.

## Stage 1 — Scaffold, schema, storage
**Prompt:** "Do Stage 1. Create the FastAPI project, pydantic models for Profile/Version/JobDescription/Application exactly per SPEC section 4, SQLite storage, `GET/PUT /profile`, config via `.env` including `LLM_PROVIDER` (gemini|groq|mistral|anthropic), and the `llm.py` wrapper: single `ask(schema, prompt)` surface, schema embedded in the prompt (no provider-specific JSON modes), one OpenAI-compatible `httpx` path for gemini/groq/mistral plus a separate Anthropic branch, parse + pydantic validate, retry once, then raise `LLMError`. Add a `--check-llm` command (tiny JSON-schema test call, prints pass/fail), pytest in requirements, and `.gitignore` for `.env`, `logs/`, `*.db`, venv. Add pytest tests; all LLM tests mocked, no real key needed."
**Acceptance:**
- App starts; `/docs` loads.
- PUT then GET a sample profile round-trips unchanged.
- Invalid profile (missing name, bad date) is rejected with a clear error.
- `llm.py` test with a mocked client: invalid JSON triggers exactly one retry, then raises.
- `--check-llm` reports pass/fail against each of the four providers using a mocked client.

## Stage 2 — Renderers (no AI yet)
**Prompt:** "Do Stage 2. Build renderers: profile/version JSON → ATS-safe PDF (Tectonic via Jinja2 LaTeX template; if Tectonic can't be installed, use HTML→PDF with WeasyPrint and tell me), DOCX (python-docx), TXT. Single column, standard headings from rules.json, escape LaTeX special characters. Add `POST /export/{version_id}`."
**Acceptance:**
- A sample profile with special characters (`& % # _ $`) renders without error in all three formats.
- PDF text is selectable; `pdfplumber` extraction returns headings in the correct order plus the email and phone.
- Sample student profile fits within the page limit from rules.json.
- DOCX opens with python-docx and contains the same text as the TXT.

## Stage 3 — Frontend: profile editor
**Prompt:** "Do Stage 3. Build the plain single-page frontend (no build step) with a collapsible section per resume section and add/remove entries/bullets, wired to GET/PUT /profile. Autosave to the backend. Add Export buttons (PDF/DOCX/TXT) and a profile JSON download/upload. No styling beyond basic readability."
**Acceptance:**
- I can enter a full profile in the browser, reload, and everything persists.
- Exporting from the browser produces valid PDF/DOCX/TXT.
- Removing/reordering entries works.

## Stage 4 — AI assist per section + interview mode
**Prompt:** "Do Stage 4. Add a 'Tell the AI' box per section. Implement `POST /assist/{section}` and `POST /assist/answer`: free text → structured entries + follow-up questions → answers → polished bullets using rules.json (verbs, banned phrases, length). Store `raw_facts` and `text` per bullet. Show results as a suggestion the user accepts/edits/rejects. Prompts live in `prompts/` as separate files with the fact-honesty rule stated explicitly."
**Acceptance:**
- Input 'worked on backend for a staffing app using FastAPI and Postgres' makes the AI ask clarifying questions rather than inventing numbers.
- After I supply numbers, the bullet contains only those numbers.
- Test: feed a prompt that tempts invention (no metrics given); output contains no digits that weren't in the input.
- No banned phrase appears in 20 sample generations (automated check).

## Stage 5 — JD analyzer + gap alerts
**Prompt:** "Do Stage 5. Implement `POST /jd/analyze` (extract title, seniority, required/preferred skills, keywords, responsibilities) and `POST /jd/gap`. Use a local skill alias table (`skills_aliases.json`) and deterministic matching first, LLM only for fuzzy cases. Output matched / missing-required / missing-preferred / 'probably have but unlisted (confirm?)'. Add the Tailor page's analysis section in the frontend. Compute keyword and requirement coverage %."
**Acceptance:**
- Using 3 real JDs I supply, extracted required skills are correct by my manual check.
- 'Postgres' in profile satisfies 'PostgreSQL' in JD, and 'JS' satisfies 'JavaScript'.
- A skill truly absent is reported missing, never auto-added to the profile.

## Stage 6 — Tailoring + versions
**Prompt:** "Do Stage 6. Implement `POST /tailor`: rank profile items by JD relevance, select under the page budget, rewrite bullets from `raw_facts` using JD vocabulary only where facts support it, reorder skills/sections, save as a named Version linked to the JD. Add preview and export on the Tailor page."
**Acceptance:**
- Tailored version fits the page limit.
- Tailored bullets differ from the base resume in vocabulary but introduce no new facts (verified in Stage 7's fact guard).
- The same profile tailored to two different JDs gives visibly different selection and ordering.
- Base profile is unchanged after tailoring.

## Stage 7 — Validators
**Prompt:** "Do Stage 7. Implement validators from SPEC section 3: fact guard (numbers/tools/employers/dates in output must exist in raw_facts or profile), ATS lint (extract PDF text, check headings/order/contact), length/layout, voice lint, consistency (dates, tense). Run automatically before export and show a report; block export on fact-guard failure."
**Acceptance:**
- Plant a fake claim ('led a team of 12') into a bullet: fact guard blocks the export.
- Plant a banned phrase: voice lint flags it.
- Plant overlapping job dates: consistency check flags it.
- A clean resume passes all checks.

## Stage 8 — Tracker + stats
**Prompt:** "Do Stage 8. Implement the application tracker (SPEC section 4 Application) with a simple table UI: add, update status, notes, filter by status. Link each entry to its version and JD."
**Acceptance:**
- Create, edit, and filter applications; links to versions work.
- Deleting a version doesn't orphan or crash the tracker.

## Stage 9 (optional, v2)
Cover letter / referral message, LinkedIn text, interview prep, cross-JD skill-gap summary, response-rate stats. One feature per prompt, same rules.

---
## Final end-to-end test
Empty profile → enter my real details (half typed, half via AI) → paste a real JD → get a gap report, a tailored one-page PDF/DOCX/TXT, a passing validation report, and a tracker entry. Read every bullet and confirm each is true.
