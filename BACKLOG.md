# BACKLOG.md — Deferred Features

These are explicitly NOT in the current stage. Do not implement until asked.

## Features

- Page Setup dialog (font, size, margins, density, date format per version)
- .tex export via Jinja2 template (keep PDF on WeasyPrint)
- Desktop cleanup (unused icons, taskbar grouping, snap-to-grid)
- More fonts beyond the ATS-safe list
- Cover letter generator
- LinkedIn "About" text generator

## Known issues found while fixing the /assist/answer 400

Not part of that fix. Recorded here rather than silently fixed.

### ~~The live-call budget is counted per layer, not per request~~ — fixed

`app/llm.CallBudget` is now one counter per press. `write_bullets` creates it and
hands it to every `ask`, and `ask` charges it before every HTTP request, so a
truncated-reply retry costs the same as the first try. `MAX_CALLS_PER_PRESS` is 3,
including that retry. A spent budget raises `CallBudgetExhausted`, which is its own
type rather than an `LLMError` — see the note below on why.

Worst case before: 2 × 2 = 4 provider calls, the whole of the old cap.

### A spent budget is not a provider failure, and that distinction is easy to lose

`CallBudgetExhausted` does not subclass `LLMError`, because every `except LLMError`
in the codebase renders the error as "[provider/model] HTTP 4xx: what the provider
said" — inventing both a culprit and a status code for something the provider never
did. The cost is that any new `except LLMError` must *not* be assumed to cover it.
`app/main.py` catches it explicitly on both AI routes and passes the sentence through
unchanged. If a third AI route is added, it needs the same pair of handlers.

### ~~`split_facts` splits a multi-fact line into overlapping facts~~ — fixed

Done: `split_facts` now strips the user's own list marker and merges a line into
the fact above it when one token set contains the other. `shared_facts` reports a
fact id cited by more than one bullet, so the failure mode is now visible even
when splitting cannot prevent it.

What is still not handled: one line that genuinely contains two claims ("owned
the billing service, a small team of 3") stays one fact, so the writer has to
split it or drop half. That needs a judgement call the caller cannot make from
tokens alone, so it stays deferred.

### The date normaliser exists twice and the drift test only checks the tables

`app/models.py:normalise_date` and `EditorModel.normaliseDate` implement the same
grammar. A drift test compares `DATE_MONTHS` to `_MONTH_NAMES` and `PRESENT_WORDS` both
ways, but the two *parsers* are still separate code: a rule added to one and not the
other (an accepted format, a refusal phrase) would pass the test. Worth collapsing onto
one definition when there is a place for it.

### `sample.js` was never re-checked against the new list rules

Skills and tech are real lists now, with duplicates dropped case-insensitively, and
links are label-plus-URL. The sample data may still contain duplicate skill items or
two-word link labels that the editor would immediately reject or reshape on load. Not
checked, because it is cosmetic.

### `tests/conftest.py` still has invented personal data

`sample_profile_payload` carries a made-up city, employer, university and phone
number. Same rule as everywhere else: neutral placeholders only. Not fixed here
because it was not part of this round's asks.

### ~~The two `explainFailure` implementations have drifted~~ — fixed

Both now read `app/static/win/failures.js`, which is DOM-free and driven for real by
`tests/test_failures.py`. The editor's copy was the weaker one: it dropped the entry
number and left `Value error,` at the front of the sentence, so the same 422 read two
different ways depending on which window ran it.

### ~~`start: "Present"` is accepted by the parser but rejected by the range check~~ — fixed

`_as_range_point` sorts `Present` after every real date, so one comparison covers both
ends. A range that opens with the open end and closes on a real day is still refused,
with a message naming which field to move where — it is nearly always the two dates
typed the wrong way round.

### `explainFailure` drops the field name from a validation error

The tail of a pydantic `loc` is dropped on the assumption that the message names the
field. Pydantic's own messages do; this project's custom `raise ValueError(...)` ones
do not — `'Jul' is not a date I can read` names no field. So two bad dates in one
entry produce two identical sentences. Not changed here because it was not part of the
merge that found it. `tests/test_failures.py` says so where the gap is.

### The three AI call timings still come from a stub

The timing fields are on every log line and the plumbing is proven, but the only real
figure is the 80-second live run from Stage 4. Nobody has seen what a normal
untruncated call costs against OpenRouter, because live calls are off. When one is
allowed, `assist.done total_ms` and `llm.ok prompt_tokens` are the numbers to read.

### The reasoning model is a poor fit for a JSON-only task

`nvidia/nemotron-3-super-120b-a12b:free` spends most of its budget on a
reasoning block and returned `content: null` twice at 2048 and 4096 tokens.
The truncation raise saved the request, but the model only answered at 8192.
Worth reconsidering `LLM_MODEL` in `.env`.