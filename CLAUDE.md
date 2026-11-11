# CLAUDE.md — read this first, every session

Project: personal AI resume builder (single user, runs locally). Full vision is in `SPEC.md`. Build order is in `BUILD_PLAN.md`. Progress is tracked in `PROGRESS.md`.

## Working rules
1. Read `SPEC.md` fully, then `PROGRESS.md`, before doing anything.
2. Work on ONE stage at a time: the one marked CURRENT in `PROGRESS.md`. Do not start the next stage, even if it looks easy.
3. Before coding a stage, write a short plan (files to create, functions, data flow) and wait for my OK.
4. A stage is done only when every acceptance test in `BUILD_PLAN.md` for that stage passes. Run them yourself and show me the output. Never claim "done" without running them.
5. After a stage passes: update `PROGRESS.md`, then `git commit -m "stage N: <name>"`. Then stop and tell me what to manually check.
6. If the spec is ambiguous, ask me. Do not guess silently.
7. Do not add dependencies without listing them and why. Prefer the standard library and the stack in `SPEC.md`.
8. Do not spend effort on visual polish. Plain, functional UI only.
9. Secrets (API keys) live in `.env`, never in code or commits.
10. Reply to my numbered asks by number. For each: "DONE" plus evidence (command output, test name, or file:line), or "NOT DONE" plus the reason. No other content. Anything not in my numbered asks goes in `BACKLOG.md`, not code.

## Non-negotiable design rules (also in SPEC.md)
- The LLM only produces TEXT FIELDS inside structured JSON. It never writes LaTeX, HTML, or layout.
- The LLM must never invent facts: no made-up employers, dates, tools, numbers, or outcomes. If a detail is missing, it asks the user.
- Every LLM call returns JSON validated against a schema (pydantic). Invalid output is retried once, then surfaced as an error.
- All hiring/ATS/resume conventions come from `RULES.md` (researched in Stage 0), not from the model's memory. Read it, don't re-derive it.
