# PROGRESS

CURRENT STAGE: 4 (AI assist per section + interview mode)

## Done
- Stage 0 (accepted): `RULES.md` + `rules.json`, 75 distinct source URLs across 56 domains, every rule `verified`/`unverified`, `rules.json` parses.
- Stage 1 (accepted): FastAPI app, pydantic models for Profile/Version/JobDescription/Application (SPEC §4), SQLite storage, `GET/PUT /profile`, provider-agnostic `llm.py`, `--check-llm`.
- Stage 2 (accepted): renderers profile/version JSON → ATS-safe PDF (WeasyPrint), DOCX (python-docx), TXT. Canonical `Doc` intermediate means DOCX and TXT are textually identical by construction. `app/rules.py` is the single loader for every convention.
- Stage 3 (accepted): single-page terminal UI at `/`, no build step, zero dependencies. **279 tests pass.**

### Stage 3 — the terminal UI
`app/static/{index.html,term.css,app.js}`, mounted at `/`, plus one new route `POST /preview`.

- **Navbar types commands instead of bypassing them.** Clicking a section runs `cd <section>` *through the terminal*, so you see the command echo. One interface, no divergence between UI and command state. Styled as a dim terminal title bar.
- **No mouse handlers** except the navbar shortcut and the two preview-bar chrome buttons. Text selection and wheel scrolling deliberately still work so bullets can be copied out. Enforced by tests.
- **Every character reaches the DOM via `textContent`.** No `innerHTML`, no `eval`. A terminal echoes user input and server output, which is exactly how terminal UIs become XSS vectors. Tests strip comments and grep for it.
- **Live preview is the real exported PDF**, rendered server-side by `POST /preview` from the body the browser holds — not an HTML approximation that could quietly disagree with the file you actually send. Reports pages/limit/budget/density live.
- **Reliability:** global `error` + `unhandledrejection` handlers, a try/catch boundary around command dispatch, guarded `localStorage` (private mode), autosave with visible `saving…/saved/save failed`, and `Ctrl+C` that discards a draft without killing the session.
- **Learnability:** `/help` and `help` both work, Tab completion for commands/sections/fields/formats/themes, Levenshtein "did you mean", state-aware `hint`, `↑`/`↓` history, `help <topic>`.
- **Undo from day one** (`u`, `Ctrl+Z`), 60-deep snapshot stack, per the decision to add it while the command set is small.
- 4 themes (`amber`/`green`/`matrix`/`paper`) via `theme <name>`, persisted. Font stack is local-only — no web font download, so offline-first survives.
- Command names chosen to survive later stages: `draft <section> --ai <text>` is the natural home for Stage 4's "Tell the AI".
- **Preview CSP bug:** the live preview rendered as a blank white pane. It is fed a `blob:` URL into an iframe, and the page CSP said `frame-src 'self'` — CSP matches `'self'` on scheme+host+port, so a `blob:` frame does not match and the browser blocked it silently, with nothing in the server log. Allowed `blob:`, added `object-src 'none'`, and gave the pane a visible `open` link plus a fallback message so a blocked preview can never again be a silent white rectangle.

### Redesign branch
`design/vintage-layout` holds an in-progress single-page redesign: early-web aesthetic, HOME / DRAFT / NEW RESUME / AI BUILDER nav, left rail, large live preview on the right, CSS/SVG-generated vintage texture. `main` stays on the working terminal design so either can be kept. The command engine, rules, renderers, API and security work are shared and unaffected by the redesign.

### Bugs found while building Stage 3
Five real defects, four fatal or silent. Static tests could not have caught them; running `app.js` under node did.
1. **Fatal:** `HELP_TOPICS.help` called `Object.keys(HELP_TOPICS)` inside its own initialiser — a temporal dead zone `ReferenceError` that killed `app.js` at load. The page would have been blank.
2. `edit` read the field name from the wrong argument index, so it was broken for *both* list and single-value sections.
3. `grade 8.7` wrote a `grade` key inside the grade object, producing `{"grade":"8.7"}` instead of `{"value":"8.7","scale":"10"}`.
4. `profile` called `outLines('', …)` with a string instead of an array, throwing `forEach is not a function` mid-command.
5. The "command not found" suggestion was missing its closing backtick — the most-read line in the app.
Also: a mistyped field inside a draft reported "command not found" instead of "unknown field"; it now reports the field error with the valid list.

### Stage 2 findings and fixes
- **Silent data loss.** `rules.json`'s `experienced` order omitted `achievements_awards` and `build_doc` iterated that list exactly, so an experienced candidate's Achievements vanished from all three formats with no error. Fixed at the root: added to both level orders, plus a machine-readable `section_order.fallback_append` rule that a populated section the order did not place is appended, never discarded. RULES.md §3 amended with an honest `unverified` tag.
- **A heading was hardcoded in Python** (`"Publications"`), which CLAUDE.md forbids. Now via `rules.heading()`.
- **Page budget ignored.** Density now scales `normal` 1.0in → `compact` 0.75in → `tight` 0.5in, never below the researched 10.5pt font or 0.5in margin minimum. 12 bullets go 2 pages → 1 page. If even `tight` overflows, export returns a valid PDF with `X-Page-Budget: over` rather than pretending.
- **`market_snapshot.stale_after` disagreed with `stale_after_days`** by 2 days and used `>` so the expiry date counted as fresh. Fixed, with a test keeping them in step.

### Stage 3b: two resume templates (`blank` and `sheets`)

The user supplied a widely used third-party format (a self-described former Fortune 100 recruiter; cited in RULES.md §3a) and asked for it to be followed.

Templates are **data in `rules.json`, never conditionals in the renderer** — CLAUDE.md rule 4 says conventions come from RULES.md, so a renderer that hardcoded "drop the summary" would be exactly the sin that rule exists to prevent.

| | `blank` | `sheets` |
|---|---|---|
| Summary | printed | hidden |
| Interests | not printed | printed last, one line |
| Page budget | 2 (experienced) | 1, whatever the level |
| Filename | `Dusht Verma.pdf` | `Dusht Verma Resume.pdf` |

The two sources genuinely disagree about summaries. That is recorded, not silently resolved: `rules.json` carries a `why_not_merge` note, RULES.md §3a documents the conflict with honest `unverified` tags, and the user picks. Switching templates never deletes anything — the summary and interests stay in the profile and are merely not printed. `profile` gained a `printed` yes/no column so this is never a surprise.

Added `Profile.interests` as a single free-text string, per the source's "a single-line Interests entry" wording.

Worth recording: that source **independently agrees** with our own §2 research that the human screener, not the ATS, is the real gate. Two unrelated sources reaching the same conclusion is the strongest signal in RULES.md.

### Stage 3c: the front-page redesign (branch `design/vintage-layout`)

Single-page layout: masthead (**Home · Draft · New Resume · AI Resume Builder**) over three columns — left rail, stage, and a permanent live preview on the right. Olive/khaki on parchment, beaded frames, polaroid panels, all imagery generated with CSS gradients and inline SVG. Nothing is downloaded, so there is no licence to honour and no request that can fail.

- Left rail: most-recent-resume polaroid, a **NEWS** panel of research-backed tips, a progress meter, the section list, an always-visible AI helper slot, and notes.
- **NEWS is served from `rules.json`**, not typed into the markup, so the advice on screen is the cited research rather than a paraphrase. Injected into an inert `<template>` with `<`/`>`/`&` escaped — no new route, so the route surface is unchanged.
- Every tip carries its `verified`/`unverified` tag on screen. Half this advice rests on a single source and the panel must not imply otherwise.
- **New Resume** offers a blank skeleton plus each named format; every button types a terminal command rather than acting.
- **AI Resume Builder** is a placeholder that says plainly it is not built and why. The provider rejects every available model, and an assistant that guesses is worse than none on a document you are about to send.
- Progress counts only sections the active template prints, so choosing `sheets` does not read as unfinished work.

Contracts deliberately unchanged: the terminal is still the only way to edit; all text still arrives via `textContent`; no inline styles or `<style>` blocks (the CSP has no `unsafe-inline`, so either would silently do nothing); text selection and wheel scrolling still work.

**"Editable" preview, honestly:** you cannot click inside a rendered PDF. The affordance is therefore an explicit section jump list beside the preview that types `cd <section>`, rather than a click target that silently does nothing.

### Findings during the redesign

Four of these were invisible to the test suite and only surfaced by screenshotting the real page in headless Chrome.

1. **Every view rendered on top of every other one.** `term.css` sets `#view-draft { display: flex }`; an id outranks `.view[hidden] { display: none }`, so the hidden attribute lost and Home and the terminal were stacked on top of each other. Fixed by making the hidden rule out-specify the id. **No test failed** — the markup, the JS and the CSS were each individually correct.
2. **The page advertised a `check` command that does not exist**, in two places, described as "every rule you are currently breaking". Caught by grepping the copy against the command table. On an app whose entire argument is that it tells you the truth about your resume, that was the worst possible place to be casual. Both mentions replaced with commands that exist, and a test now parses the `COMMANDS` object and fails if the page ever names a command that is not in it.
3. `THEMES` listed four palettes while the CSS defined five, so `vintage` could not be selected.
4. The scanline overlay moved from `body` to the terminal view; left on `body` it would have sat over the whole page.

Two of my own earlier guards fired correctly and were rewritten rather than deleted — but honestly:

- `test_no_mouse_handlers_beyond_the_agreed_chrome` asserted an **exact list of three click listeners**. That froze a UI which had exactly three controls; the redesigned page legitimately has more. Rewritten to assert on the *set of event types* plus a new test that classifies every click registration into one of three permitted shapes (types a command / controls the preview / only changes what is displayed). The real guarantee is kept; the brittle count is gone.
- The test forbidding `@import` was failing because the word appeared in a **CSS comment**. Reworded the comment rather than the test — the ban is about remote fonts, and the comment was accurate.

Also worth recording from the earlier template work: **two existing tests were asserting a buggy data shape** (`summary` stored as `{text: ...}` instead of a string). A test that pins incorrect behaviour is indistinguishable from one that protects correct behaviour.

### Security pass (tests in `tests/test_security.py`)
DNS rebinding closed with `TrustedHostMiddleware`; over-nested JSON (~6KB of `[`) caused a 500 + traceback, now 422; invisible/control characters (NUL, U+202E, zero-width, bidi isolates, BOM, DEL) rejected naming the code point; list fields capped 60/12/20. Security headers on every response with **two CSPs** — `default-src 'none'` for API routes, `default-src 'self'` for the page (the strict API policy would otherwise have blanked the UI). Exports sent `no-store`. Verified **not** vulnerable with tests: SQL injection (queries parameterised), CORS absent by design, no secret in any response.

## Commands
- install: `python -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt`
- tests: `.venv\Scripts\python -m pytest`
- **app + UI: `.venv\Scripts\python -m uvicorn app.main:app --reload`, open http://localhost:8000**
- check LLM: `.venv\Scripts\python -m app.cli --check-llm`
- terminal flow tests need node; they skip automatically without it

- **Visual verification found what tests could not.** Headless Chrome (`--screenshot`, `--dump-dom`) is available on this machine and is how the stacked-views bug and the phantom `check` command were caught. Worth repeating for any UI change; a redesign that passes 415 tests can still be visibly broken.
- `tests/check_static.py` is a standalone script (not pytest) that cross-checks `app.js`, `index.html` and both stylesheets: every id JS asks for exists, the palette is defined in exactly one file, the two themes lists agree, and no stylesheet reaches outside. Catches the most common silent redesign failure — JS reaching for an element the new markup does not have.

## Notes / decisions
- One stage at a time (CLAUDE.md rule 2): no speculative endpoints or helpers for later stages. `test_stage3_exposes_only_its_own_routes` and `test_later_stage_routes_are_absent` fail if they creep back.
- rules.json is a summary of RULES.md; RULES.md is prose-of-truth. `app/rules.py` is the only reader, so no convention is ever taken from model memory.
- **CLAUDE.md rule 8 (no visual polish) was overridden once, by the user, for Stage 3 only.** Kept cheap: CSS custom properties, no theming framework, no dependencies.
- **PDF engine: WeasyPrint, chosen on measurement.** Tectonic + Calibri dropped *every word space* in text extraction, keeping 9/20 content canaries; WeasyPrint kept 19/19 and renders in ~260ms vs ~4.7s.
- **Bullets are a literal ASCII hyphen**, not a CSS list marker: a generated `•` extracts as U+FFFD and garbles ATS parsing. Implements RULES.md §2.
- `llm.py`: `ask(schema, prompt)` only. Schema embedded in the prompt, no provider JSON modes. Retry once, then `LLMError`.
- Tests fake `httpx.Client` (tests/fakes.py) rather than `respx`, and assert the *number* of HTTP calls, which is the retry-once contract.
- Dates are ISO strings validated by regex, so `2022-07` is valid without inventing day numbers. Rendered `Jul 2022`, never `'22`.

## Known issues
- **BLOCKER for Stage 4:** the configured Gemini project returns 403 "Your project has been denied access" for all Gemini 3.x models, and the 2.5 family is retired for new accounts. Enable access in Google AI Studio / Cloud console, or point `LLM_PROVIDER` at another provider. All code paths are proven by mocks; only the live wire format is unverified. **Stage 4 cannot be verified end-to-end until this is resolved.**
- A resume genuinely longer than the page budget still exports over budget with `X-Page-Budget: over`. Intentional — Stage 6 does deliberate trimming.
- `POST /versions` is unbounded, so versions accumulate. A cap now would become a bug in Stage 6, where tailoring legitimately creates many; revisit with retention in Stage 8.
- Python 3.14; starlette warns `httpx` with `TestClient` is deprecated in favour of `httpx2`. Harmless now.
- Undo is per-browser-tab and not persisted across reloads. Acceptable while small; may want a server-side store later.
