# SPEC — Personal AI Resume Builder

## 1. Goal
A local tool that turns a person's raw experience into a resume that gets interviews. The user either types each section or describes it casually and the AI writes it. Pasting a job description tailors the resume and flags missing skills. Priority: **performance and correctness over looks.** Single user, personal use, no auth, no deployment.

## 2. Core principles
1. **Truth first.** Every claim in the output traces to something the user said. The AI polishes and selects; it never fabricates.
2. **Structure over free text.** The resume is a JSON document (the "profile"). Renderers turn it into files. The LLM only fills text strings inside it.
3. **ATS-safe by construction.** Single column, standard headings, selectable text, no tables/icons/images in the ATS version.
4. **Sounds human.** Specific nouns and numbers, varied sentence openings, no buzzword filler. We do NOT build "AI detector evasion"; detectors are unreliable and recruiters rarely run them. Specificity and the user's own facts are the fix.
5. **Evidence-based.** Conventions (length, sections, keywords, India vs global differences) come from `RULES.md`, produced by a research stage with cited sources, and updated when stale.

## 3. Features

### v1 (build these)
- **Profile editor (frontend):** sections: Contact/Links, Summary, Education, Work Experience, Internships, Projects, Skills, Certifications, Achievements/Extracurriculars, optional Publications. Each entry has structured fields plus bullets.
- **Dual input per section:** (a) manual typing, or (b) "Tell the AI": free-text/voice-style dump → AI returns structured entries and polished bullets, shown as a **diff-style suggestion the user accepts, edits, or rejects**. Nothing is saved without acceptance.
- **Interview mode:** when the AI sees a vague item ("worked on backend"), it asks 2–4 targeted questions (scale? tools? measurable result? your role vs team?) to extract real metrics, then writes the bullet. Missing numbers are asked for, never invented.
- **Bullet writer rules:** action verb + what + how/tool + measurable result; one line to two lines max; no banned phrases (list in `RULES.md`); varied verbs; no repeated opening word within a section.
- **JD tailoring:** paste a job description (or URL text) → extract title, seniority, required vs preferred skills, keywords, responsibilities → select and reorder the most relevant profile items, rewrite bullets to mirror the JD's vocabulary **only where the user's facts support it** → produce a tailored resume version.
- **Gap alerts:** compare JD requirements to the profile. Output: matched, missing-but-required, missing-but-preferred, and "you likely have this but didn't list it" (asks the user to confirm). For truly missing skills, give a short honest note (e.g. "not in your profile; don't add unless true; typical way to gain it").
- **Match score:** keyword coverage % and requirement coverage % per tailored version, with reasons.
- **Validators (run before any export; enforce by rule tag):**
  - **Grounding in `RULES.md`/`rules.json`:** every validator rule carries a `verified`/`unverified` tag from `rules.json`. Violations of `verified` rules **block the export**; violations of `unverified` rules produce **warnings only**.
  - Fact guard: every number, tool, employer, date in the output exists in the profile.
  - ATS lint: re-extract text from the generated PDF; confirm headings, order, email/phone parse.
  - Length/layout: page count within `RULES.md` limits; no orphan lines.
  - Voice lint: banned phrases, repeated openers, bullets lacking a concrete noun or number.
  - Consistency: date formats, tense (past for old roles, present for current), no overlapping/conflicting dates.
- **Export:** PDF (primary, via LaTeX or HTML→PDF), DOCX, plain TXT. Also JSON export of the profile for backup.
- **Versions:** each tailored resume is saved as a named version linked to the JD it targeted.
- **Application tracker:** company, role, JD, version used, date applied, source (referral/portal/LinkedIn/Naukri), status, notes. Simple table view.

### v2 (only after v1 works)
- Cover letter / referral-message / recruiter cold-DM generator from profile + JD.
- LinkedIn headline + About section generator from the profile.
- Interview prep: likely questions from the JD plus the user's own projects as answer material.
- Response-rate stats: which version/source gets replies.
- Skill-gap learning suggestions aggregated across many saved JDs ("you're missing X in 7 of 10 JDs").

## 4. Data model (profile JSON, validate with pydantic)
```
Profile
  contact: name, email, phone, location(city, country), links[{label,url}]
  summary: str (optional, 2-3 lines)
  education[]: institution, degree, field, start, end, grade{value, scale}, coursework[], notes
  experience[]: org, role, type(job|internship|freelance), location, start, end|"Present",
                bullets[{id, raw_facts, text, metrics[], tags[], tools[]}]
  projects[]: name, role, links[], start, end, tech[], bullets[same as above]
  skills: groups[{name, items[]}]
  certifications[], achievements[], extracurriculars[]
Version
  id, name, profile_snapshot, jd_id|null, template, created_at, validation_report
  include_personal_details: bool = false   # when true, also render optional personal-details data (below)
JobDescription: id, raw_text, parsed{title, seniority, required[], preferred[], keywords[], responsibilities[]}
Application: id, company, role, jd_id, version_id, applied_on, source, status, notes
```
**Personal details block (optional, per version).** Fields: photo, date_of_birth, gender, marital_status, father's name, and Class 10/12 marks as an optional education sub-section. These are legacy Indian biodata conventions (see RULES.md §9) and are **off by default** (`include_personal_details: false`). They are stored in the Profile but rendered only when a version sets the toggle to true (use cases: Indian campus/service-company drives or forms that explicitly ask). These fields are omitted from fact-guard/scoring expectations and never auto-added.
Key point: each bullet stores **`raw_facts` (what the user actually said) and `text` (the polished version)**. The fact guard checks `text` against `raw_facts`. Tailoring rewrites from `raw_facts`, never from earlier polished text, so wording doesn't drift.

## 5. Pipelines
1. **AI assist:** user text → LLM (schema-constrained) → candidate entries + follow-up questions → user answers → candidate bullets → fact guard → show suggestion → user accepts.
2. **JD analysis:** JD text → LLM extraction (schema) → normalize skills (synonyms: "JS"="JavaScript", "Postgres"="PostgreSQL") with a local alias table.
3. **Gap analysis:** deterministic matching first (alias table + string match), LLM only for fuzzy cases. Output matched/missing lists.
4. **Tailoring:** rank profile items by relevance to JD → keep top N under the length budget → rewrite bullets from `raw_facts` using JD vocabulary where true → reorder sections/skills → validators → save version.
5. **Render:** version JSON → Jinja2 template → LaTeX → PDF (Tectonic), plus python-docx and TXT. Fallback if LaTeX is a pain: HTML → PDF via WeasyPrint. Keep one ATS-safe template per format.

## 6. Tech stack
- Python 3.11+, **FastAPI**, SQLite (via SQLModel or plain sqlite3), pydantic.
- Frontend: **single-page, no build step** (plain HTML + small vanilla JS or htmx). No React unless needed.
- LLM: Anthropic API (key in `.env`). One `llm.py` wrapper with: JSON-schema output, retry-once on invalid JSON, a model-name config, request logging to file for debugging.
- Rendering: Jinja2, Tectonic (LaTeX→PDF), python-docx, pdfplumber (for ATS lint text extraction).
- Run: `uvicorn app.main:app --reload`, open `localhost:8000`.

## 7. API (suggested)
`GET/PUT /profile` · `POST /assist/{section}` · `POST /assist/answer` · `POST /jd/analyze` · `POST /jd/gap` · `POST /tailor` · `POST /validate/{version_id}` · `POST /export/{version_id}?format=pdf|docx|txt` · `GET/POST /versions` · `GET/POST/PATCH /applications`

## 8. Frontend pages (plain)
1. **Profile:** one page, collapsible section per resume section; each has the manual form and a "Tell the AI" box.
2. **Tailor:** paste JD → analysis, gap alerts, match score → "Create tailored version" → preview text + validation report → export buttons.
3. **Versions & tracker:** table of versions and applications.

## 9. Research requirements (Stage 0 produces `RULES.md`)
Use web search; cite every rule with a source URL and date; mark each rule `verified` or `unverified`. Cover:
- Recruiter screening behavior: time per resume, what they look at first, preferred length by experience level.
- ATS behavior: common systems, parsing pitfalls, safe headings, fonts, file types.
- **Global vs India differences.** Hypotheses to verify, not assume: Indian freshers often list CGPA/percentage and 10th/12th marks (campus/service-company norms); photo, date of birth, gender, marital status, and father's name are common in older Indian formats but discouraged for global/ATS applications; Naukri/LinkedIn/Foundit parsing behavior; GitHub/portfolio expectations for tech roles; one-page norm for freshers.
- Fresher/student specifics: how to present internships (including unpaid), projects, coursework, and open-source when work experience is thin.
- Tech-role specifics: what recruiters look for in projects, metrics, links, tech stacks.
- Writing rules: strong verbs, quantification patterns, banned/overused phrases, tense, bullet length and count per role.
- Job market snapshot: in-demand skills for the user's target roles in India and globally, with source dates. Flag that this snapshot goes stale; include a `refresh_market_data` task.
- Honest note on AI-written resume detection and recruiter attitudes toward AI-written resumes.

## 10. Non-goals
- No auth, multi-user, payments, or deployment.
- No visual design work; templates must be plain and ATS-safe.
- No fabricating experience, and no "beat the AI detector" tricks.
- No auto-applying to jobs.

## 11. Definition of done (v1)
Starting from an empty profile, the user enters their real details (by typing and by talking to the AI), pastes a real JD, and gets within a few minutes: a one-page tailored PDF/DOCX/TXT, a gap report listing missing skills, a passing validation report, and a saved tracker entry, with no invented facts anywhere.
