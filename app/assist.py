"""AI-assist for resume sections.

Pure logic over a profile — no DOM, no framework. The UI calls these
functions; tests inject a fake ``ask`` callable; production uses
``app.llm.ask``.

Public surface::

    from app.assist import ask_clarifying, write_bullets
    questions = ask_clarifying("experience", "worked on backend...", llm=my_ask)
    bullets = write_bullets("experience", raw_facts, llm=my_ask)
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable, TypeVar

from pydantic import BaseModel, Field, ValidationError, model_validator

from . import rules

logger = logging.getLogger("app.assist")

T = TypeVar("T", bound=BaseModel)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ExtractedEntry(BaseModel):
    """One structured entry from a free-text dump."""

    org: str = ""
    role: str = ""
    start: str = ""
    end: str = ""
    bullets: list[str] = Field(default_factory=list)


class ExtractResult(BaseModel):
    """Output of POST /assist/{section}: what we understood + what we need."""

    entries: list[ExtractedEntry] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class SuggestedBullet(BaseModel):
    """One suggested bullet plus the ids of the user's facts it uses.

    ``facts`` is filled by the model and then sanitised server-side: an id
    outside 1..len(facts) is dropped rather than shown, because a label that
    points at a fact the user never gave is worse than no label.
    """

    text: str = ""
    facts: list[int] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _from_bare_string(cls, data: object) -> object:
        """Accept a plain string so a model that ignores the shape still works."""
        if isinstance(data, str):
            return {"text": data, "facts": []}
        return data


class BulletsResult(BaseModel):
    """Output of POST /assist/answer: polished bullets, with fact bookkeeping.

    ``numbered_facts`` is the user's own words, one per line, in the order the
    model was shown them. ``unused_facts``, ``reused_metrics`` and
    ``shared_facts`` are computed here, not trusted from the model, because all
    three are warnings and a warning the model made up is worse than no warning.
    """

    bullets: list[SuggestedBullet] = Field(default_factory=list)
    numbered_facts: list[str] = Field(default_factory=list)
    unused_facts: list[int] = Field(default_factory=list)
    reused_metrics: list[str] = Field(default_factory=list)
    shared_facts: list[int] = Field(default_factory=list)

    @property
    def texts(self) -> list[str]:
        return [b.text for b in self.bullets]

    @model_validator(mode="before")
    @classmethod
    def _from_bare_list(cls, data: object) -> object:
        """Accept ``["bullet", ...]`` from a model that skips the wrapper."""
        if isinstance(data, list):
            return {"bullets": data}
        return data


# ---------------------------------------------------------------------------
# Robust JSON extraction
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _balanced_candidates(text: str) -> list[str]:
    """Find all top-level {...} blocks by counting braces."""
    candidates: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    candidates.append(text[start : i + 1])
                    start = -1
    return candidates


def extract_schema_json(text: str, schema: type[T]) -> T:
    """Try progressively more aggressive strategies to find a JSON object
    that validates against ``schema``.

    Models that print reasoning text may wrap the real JSON in prose or emit
    multiple objects. We try, in order:
      1. Fenced ```json ... ``` block
      2. Whole text after stripping, as a JSON object
      3. First '{' to last '}'
      4. Every balanced-brace candidate, in order

    Returns the first candidate that validates. Raises ValueError if none do.
    """
    if not text or not text.strip():
        raise ValueError("empty response")

    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1)

    candidates: list[str] = []

    # 1. Whole text
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        candidates.append(stripped)

    # 2. First { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    # 3. All balanced candidates
    candidates.extend(_balanced_candidates(text))

    for cand in candidates:
        try:
            # Try as object first
            if cand.strip().startswith("["):
                # BulletsResult wraps a list — try as list
                parsed = schema.model_validate(json.loads(cand))
                return parsed
            parsed = schema.model_validate_json(cand)
            return parsed
        except (json.JSONDecodeError, ValidationError):
            continue

    raise ValueError(f"no valid JSON matching schema found in response: {text[:200]!r}")


def extract_json(text: str) -> str:
    """Legacy extraction: first { to last }. Kept for backward compat."""
    if not text or not text.strip():
        raise ValueError("empty response from provider")

    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object found in response: {text[:200]!r}")
    return text[start : end + 1]


# ---------------------------------------------------------------------------
# Fact guard
# ---------------------------------------------------------------------------

# Number words that could appear in output but not in input
_NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "twenty", "thirty", "forty", "fifty",
    "hundred", "thousand", "million", "billion", "several", "many",
    "few", "dozen", "couple",
}

# Percent pattern
_PCT_RE = re.compile(r"\d+%")

# Digit run pattern
_DIGIT_RUN_RE = re.compile(r"\d+")


def _tokens(text: str) -> set[str]:
    """Lowercase word tokens, stripped of punctuation."""
    return set(re.findall(r"[a-z][a-z'-]{1,}", text.lower()))


def invented_digits(output: str, source: str) -> list[str]:
    """Return digit-runs in output that do not appear in source."""
    out_digits = set(_DIGIT_RUN_RE.findall(output))
    src_digits = set(_DIGIT_RUN_RE.findall(source))
    return sorted(out_digits - src_digits)


def invented_number_words(output: str, source: str) -> list[str]:
    """Return number-words in output that do not appear in source."""
    out_tokens = _tokens(output)
    src_tokens = _tokens(source)
    return sorted((out_tokens & _NUMBER_WORDS) - src_tokens)


def invented_percents(output: str, source: str) -> list[str]:
    """Return percent signs in output not in source."""
    out_pcts = set(_PCT_RE.findall(output))
    src_pcts = set(_PCT_RE.findall(source))
    return sorted(out_pcts - src_pcts)


# Proper-noun / tool heuristic: capitalized words in output not in source.
#
# A capital letter is not evidence of a proper noun. Every bullet starts with one,
# and English capitalises the first word of a clause as a matter of grammar, so
# the three words the live run actually flagged -- "Collaborated", "Helped",
# "Served" -- were all sentence-initial verbs that the guard read as invented
# tools. Worse, it burned a retry on a perfectly good reply.
#
# So a capitalised word is only a candidate if it is NOT in initial position. It
# is then checked against the source case-insensitively, because a user who typed
# "redis" and got "Redis" back has not invented anything.
_PROPER_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")
_INITIAL_POS_RE = re.compile(r"(?:^|[.!?;:\u2014\u2013-]\s*|\n\s*|\(\s*|\"\s*)$")

# Mid-sentence capitalised verbs and ordinary words that are not proper nouns.
# Sentence position handles the opening word; this handles the ones that appear
# after a clause boundary, which is where "Built ... with Redis" would otherwise
# report "Built" once the source did not contain it.
_NOT_A_PROPER_NOUN = {
    # function words
    "The", "In", "At", "On", "For", "To", "With", "From", "By", "A", "An",
    "And", "Or", "But", "As", "Its", "It", "Their", "Our", "Your", "This",
    "That", "These", "Those", "There", "Then", "Than", "When", "While",
    "After", "Before", "During", "Over", "Under", "Between", "Through",
    "Against", "Without", "Within", "Across", "Per", "Via", "Of", "Up", "Down",
    "Out", "Off", "All", "Both", "Each", "Every", "Some", "Any", "No", "Not",
    "Also", "Plus", "Since", "Because", "If", "So", "Yet", "Still", "Each",
    # past participles and plain verbs that open or continue a bullet
    "Built", "Led", "Designed", "Implemented", "Automated", "Reduced",
    "Increased", "Improved", "Launched", "Developed", "Deployed",
    "Integrated", "Scaled", "Measured", "Cut", "Accelerated", "Refactored",
    "Streamlined", "Delivered", "Owned", "Partnered", "Coordinated",
    "Documented", "Tested", "Instrumented", "Trained", "Mentored",
    "Architected", "Optimized", "Optimised", "Debugged", "Shipped",
    "Migrated", "Worked", "Handled", "Created", "Managed", "Collaborated",
    "Helped", "Served", "Supported", "Reviewed", "Audited", "Reported",
    "Analysed", "Analyzed", "Maintained", "Diagnosed", "Resolved", "Fixed",
    "Rewrote", "Ported", "Rolled", "Ran", "Wrote", "Drove", "Led", "Set",
    "Grew", "Cut", "Won", "Earned", "Gained", "Saved", "Removed", "Added",
    # nouns that appear capitalised at a clause start
    "Result", "Results", "Number", "Numbers", "Total", "Average", "Peak",
    "Time", "Times", "Work", "Users", "Teams", "Days", "Weeks", "Months",
    "Years", "Hours", "Money", "Cost", "Costs", "Speed", "Latency", "Load",
}


def _capitalised_candidates(text: str) -> set[str]:
    """Capitalised words in `text` that are not in sentence-initial position."""
    found: set[str] = set()
    for match in _PROPER_RE.finditer(text):
        # `_INITIAL_POS_RE` is anchored to the end, so test the text just before
        # the match: if that ends in a clause boundary or start-of-string, the
        # capital letter is grammatical and carries no information.
        before = text[: match.start()]
        if _INITIAL_POS_RE.search(before):
            continue
        found.add(match.group(0))
    return found


def invented_proper_nouns(output: str, source: str) -> list[str]:
    """Capitalised words in the output that the user never said, in any case.

    Reports a tool or employer the writer introduced on its own -- "Redis" when
    the source only ever said FastAPI and Postgres. Does not report ordinary
    capitalised English, because a capital letter at the start of a bullet is
    how English works and reading it as a proper noun once cost a wasted retry.
    """
    out_props = _capitalised_candidates(output)
    # Compared case-insensitively against the WHOLE source, not just its
    # capitalised words: a user who typed "redis" has named Redis, and reporting
    # it back as invented is the same bug one case-fold away.
    src_all = set(re.findall(r"[a-z0-9%.]+", source.lower()))
    fresh = {w for w in out_props if w.lower() not in src_all}
    return sorted(fresh - _NOT_A_PROPER_NOUN)


# ---------------------------------------------------------------------------
# Mechanism watchlist
# ---------------------------------------------------------------------------

# A writer will happily attach a mechanism to a tool: "Redis" becomes "Redis
# caching" and "Postgres" becomes "Postgres indexing". The user never said it,
# so it is invented fact with a plausible shape -- the hardest kind to spot by
# eye. Each entry is a family, so "caching", "cached" and "cache" are one rule.
# If the user said any member of the family, the family is allowed.
_MECHANISM_FAMILIES: dict[str, str] = {
    "caching": r"cach(?:e|es|ed|ing)",
    "indexing": r"index(?:es|ed|ing)",
    "async": r"async(?:hronous(?:ly)?)?",
    "queueing": r"queu(?:e|es|ed|ing)",
    "load balancing": r"load[- ]balanc(?:e|ed|ing)",
    "sharding": r"shard(?:s|ed|ing)",
    "replication": r"replicat(?:e|es|ed|ing|ion)",
    "batching": r"batch(?:es|ed|ing)?",
    "memoization": r"memoiz(?:e|es|ed|ing|ation)",
    "connection pooling": r"pool(?:s|ed|ing)",
    "throttling": r"throttl(?:e|es|ed|ing)",
    "debouncing": r"debounc(?:e|es|ed|ing)",
    "retrying": r"retr(?:y|ies|ied|ying)",
    "parallelising": r"parallelis(?:e|es|ed|ing)|paralleliz(?:e|es|ed|ing)",
    "lazy loading": r"lazy[- ]load(?:ed|ing)?",
    "prefetching": r"pre-?fetch(?:ed|ing)?",
    "compaction": r"compact(?:s|ed|ing|ion)?",
}

_MECHANISM_RES = {k: re.compile(v, re.IGNORECASE) for k, v in _MECHANISM_FAMILIES.items()}


def invented_mechanisms(output: str, source: str) -> list[str]:
    """Return mechanism names in output that the user never mentioned.

    The regression case is the real one: the user lists "FastAPI, Postgres,
    Redis" and a page-load figure, and the writer returns "Optimized API
    performance with Redis caching". "caching" is in the output and not in the
    input, so it is reported.
    """
    found: list[str] = []
    for label, rx in _MECHANISM_RES.items():
        if rx.search(output) and not rx.search(source):
            found.append(label)
    return sorted(found)


def fact_guard(output: str, source: str) -> list[str]:
    """Run all fact-guard checks. Returns list of problems (empty = OK)."""
    problems: list[str] = []
    digits = invented_digits(output, source)
    if digits:
        problems.append(f"invented digits: {digits}")
    num_words = invented_number_words(output, source)
    if num_words:
        problems.append(f"invented number words: {num_words}")
    pcts = invented_percents(output, source)
    if pcts:
        problems.append(f"invented percents: {pcts}")
    props = invented_proper_nouns(output, source)
    if props:
        problems.append(f"invented proper nouns/tools: {props}")
    mechanisms = invented_mechanisms(output, source)
    if mechanisms:
        problems.append(f"invented mechanism words: {mechanisms}")
    return problems


# ---------------------------------------------------------------------------
# Fact bookkeeping: which facts each bullet uses, which metric is reused
# ---------------------------------------------------------------------------


# The user numbers their own facts ("1. I own the billing service") and so do
# the follow-up answers, because the questions we asked were numbered. Keeping
# that marker in the fact text means fact 4 reads "1. 120 recruiters" -- the
# number the model sees in the body is not the id it is supposed to cite, and
# the two drift apart. Strip it and renumber.
_LIST_MARKER = re.compile(r"^\s*(?:[-*\u2022\u2013\u2014]\s+|\(?\d{1,2}[.)]\s+)")


def _tokens(text: str) -> set[str]:
    """Lowercased word set, numbers kept -- they are part of what makes a fact
    the same fact."""
    return set(re.findall(r"[a-z0-9%.]+", text.lower()))


def _is_metric_fact(text: str) -> bool:
    """Whether the fact is a bare figure rather than a claim.

    "120 recruiters" is a number the user supplies; it can legitimately appear
    under two bullets that each make a different claim about it. "I owned the
    billing service" is a claim, and two bullets both resting on it are the same
    achievement written twice.
    """
    words = [w for w in re.findall(r"[A-Za-z]+", text)]
    return bool(metric_keys(text)) and len(words) <= 3


def split_facts(source: str) -> list[str]:
    """Split the user's raw words into one fact per distinct claim.

    A line is not automatically a fact. The live run sent:

        worked on backend for a staffing app using FastAPI and Postgres
        1. 120 recruiters
        2. FastAPI, Postgres, Redis
        3. cut page load from 2s to 400ms
        4. my part, small team of 3
        1. my part was the billing service
        2. cut page load from 2s to 400ms

    which is six lines but only five distinct claims -- line 3 and line 6 say
    the same thing, and line 6 is the answers block restating line 4. Numbering
    those six gave the model two ids for one claim and two ids for one metric,
    and it duly cited both on different bullets.

    So: strip the user's own list marker, then merge a line into the fact above
    it when it says the same thing. Same thing means the same tokens, or the same
    tokens plus a few -- a claim restated with a detail added is still one claim.
    """
    lines = [_LIST_MARKER.sub("", raw).strip() for raw in source.splitlines()]
    lines = [ln for ln in lines if ln]

    facts: list[str] = []
    seen_tokens: list[set[str]] = []
    for line in lines:
        toks = _tokens(line)
        if not toks:
            continue
        duplicate_of = None
        for i, prev in enumerate(seen_tokens):
            if toks == prev:
                duplicate_of = i
                break
            # One contained in the other: a restatement, not a new claim.
            if toks <= prev or prev <= toks:
                duplicate_of = i
                break
        if duplicate_of is None:
            facts.append(line)
            seen_tokens.append(toks)
            continue
        i = duplicate_of
        # Keep the longer wording -- it carries the extra detail -- but only if
        # it is actually longer in content.
        if len(_tokens(facts[i]) | toks) > len(seen_tokens[i]):
            facts[i] = line
            seen_tokens[i] = toks | seen_tokens[i]
    return facts


def shared_facts(
    numbered: list[str], bullets: list["SuggestedBullet"]
) -> list[int]:
    """Ids cited by more than one bullet, where the fact is not a bare metric.

    Two bullets resting on the same claim are the same achievement written
    twice. Sharing a bare figure is different: "120 recruiters" is context the
    user supplied, and two distinct claims can legitimately both be measured
    against it.
    """
    counts: dict[int, int] = {}
    for b in bullets:
        for i in set(b.facts):
            counts[i] = counts.get(i, 0) + 1
    out = []
    for i, n in sorted(counts.items()):
        if n > 1 and 1 <= i <= len(numbered) and not _is_metric_fact(numbered[i - 1]):
            out.append(i)
    return out


def fact_block(facts: list[str]) -> str:
    """Render facts as a numbered list for the prompt."""
    return "\n".join(f"{i}. {text}" for i, text in enumerate(facts, start=1))


# A metric is a number plus the unit that gives it meaning. Units are
# canonicalised so "2 seconds" and "2s" are the same metric, which is the whole
# point: the writer should not spend the same figure on two bullets in two
# notations.
_UNIT_CANON = {
    "millisecond": "ms", "milliseconds": "ms", "msec": "ms", "msecs": "ms", "ms": "ms",
    "second": "s", "seconds": "s", "sec": "s", "secs": "s", "s": "s",
    "minute": "min", "minutes": "min", "mins": "min", "min": "min",
    "hour": "h", "hours": "h", "hrs": "h", "hr": "h", "h": "h",
    "day": "d", "days": "d", "d": "d",
    "week": "wk", "weeks": "wk", "wk": "wk",
    "month": "mo", "months": "mo", "mo": "mo",
    "year": "yr", "years": "yr", "yr": "yr",
    "%": "%",
}
_UNIT_ALT = "|".join(
    re.escape(u) for u in sorted(_UNIT_CANON, key=len, reverse=True)
)
_METRIC_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(%|" + _UNIT_ALT + r"|[a-z]+)?", re.IGNORECASE)


def metric_keys(text: str) -> set[str]:
    """Return the metric keys in a piece of text, e.g. {'400ms', '120recruiters'}."""
    keys: set[str] = set()
    for m in _METRIC_RE.finditer(text):
        number = m.group(1)
        raw_unit = (m.group(2) or "").lower()
        unit = _UNIT_CANON.get(raw_unit, raw_unit)
        keys.add(f"{number}{unit}")
    return keys


def reused_metrics(bullets: list[str]) -> list[str]:
    """Return metric keys that appear in more than one bullet.

    "No two bullets may reuse the same metric": if a figure is spent twice,
    the resume is padding and the reader is being asked to value the same
    achievement twice.
    """
    counts: dict[str, int] = {}
    for b in bullets:
        for k in metric_keys(b):
            counts[k] = counts.get(k, 0) + 1
    return sorted(k for k, c in counts.items() if c > 1)


def unused_facts(numbered: list[str], bullets: list["SuggestedBullet"]) -> list[int]:
    """Return 1-based ids of the user's facts no bullet used."""
    used: set[int] = set()
    for b in bullets:
        used.update(b.facts)
    return [i for i in range(1, len(numbered) + 1) if i not in used]


def _sanitise_fact_ids(bullets: list["SuggestedBullet"], total: int) -> None:
    """Drop fact ids that point outside the list of facts the user gave."""
    for b in bullets:
        seen: set[int] = set()
        kept: list[int] = []
        for i in b.facts:
            if 1 <= i <= total and i not in seen:
                seen.add(i)
                kept.append(i)
        b.facts = kept


# ---------------------------------------------------------------------------
# Banned-phrase + AI-tell guards (production, every response)
# ---------------------------------------------------------------------------


def banned_phrases_found(text: str) -> list[str]:
    """Return which banned phrases appear in the text."""
    t = text.lower()
    return [p for p in rules.load_rules()["banned_phrases"] if p in t]


def ai_tells_found(text: str) -> list[str]:
    """Return which AI-tell words appear in the text."""
    t = text.lower()
    tell_words = rules.load_rules().get("bullet_rules", {}).get("ai_tells", {}).get("words", [])
    return [w for w in tell_words if w in t]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def ask_clarifying(
    section: str,
    free_text: str,
    *,
    llm: Callable[[type[T], str], T] | None = None,
) -> ExtractResult:
    """Step 1: extract structured entries + ask follow-up questions.

    ``llm`` is injectable for testing. In production it is ``app.llm.ask``.
    """
    from .llm import ask  # local import to avoid circular at module load

    ask_fn = llm or ask

    # Scope check
    scope = rules.load_rules().get("ai_scope", {})
    writable = scope.get("bullet_writing_sections", [])
    structure_only = scope.get("structure_only_sections", [])
    if section in structure_only:
        # For Education/Contact, extract only — no questions, no polishing
        prompt = _load_prompt("extract.md") + f"\n\nInput:\n{free_text}"
        return ask_fn(ExtractResult, prompt)

    if section not in writable:
        raise ValueError(f"Section '{section}' is not supported for AI assist")

    prompt = _load_prompt("extract.md") + f"\n\nInput:\n{free_text}"
    return ask_fn(ExtractResult, prompt)


def write_bullets(
    section: str,
    raw_facts: str,
    answers: str = "",
    *,
    llm: Callable[[type[T], str], T] | None = None,
) -> BulletsResult:
    """Step 2: polish facts into bullets. Fact-guard and banned-phrase
    checks run on every response; on failure the whole thing is retried once.

    The user's words are numbered and sent to the model, which must say which
    facts each bullet uses. Fact ids are sanitised, unused facts and reused
    metrics are computed here, and the result carries both so the UI can show
    what the bullets are built from and what they left out.

    One press, one budget. This function's retry loop and `llm.ask`'s retry loop
    used to count independently, so the worst case was their product and
    neither could see the other. The budget is created here and handed to every
    `ask` below; a budget that ran out raises rather than stopping quietly.
    """
    # Local import to avoid a circular import at module load.
    from .llm import CallBudget, CallBudgetExhausted, ask

    ask_fn = llm or ask

    # Scope check
    scope = rules.load_rules().get("ai_scope", {})
    writable = scope.get("bullet_writing_sections", [])
    if section not in writable:
        raise ValueError(f"Section '{section}' does not support bullet writing")

    source = f"{raw_facts}\n{answers}" if answers else raw_facts
    facts = split_facts(source)
    prompt = (
        _load_prompt("write_bullets.md")
        + f"\n\nFacts (numbered; use these numbers):\n{fact_block(facts)}"
    )

    last_error = ""
    started = time.monotonic()
    # One budget for the whole press, shared with llm.ask. Created here, not
    # inside the loop, and passed to every call below.
    budget = CallBudget()
    for attempt in range(2):  # max 2 calls to ask(), which shares this budget
        attempt_started = time.monotonic()
        try:
            result = ask_fn(BulletsResult, prompt, budget=budget)
        except Exception as exc:
            # A budget that has run out is the whole answer: retrying cannot
            # help, and the message it carries is the one to show. Matched on
            # the type, not on `provider == "budget"` -- a provider name is a
            # wire value, and this one is allowed to stop a retry.
            if isinstance(exc, CallBudgetExhausted):
                logger.warning(
                    "assist.budget_exhausted section=%s calls=%d total_ms=%d",
                    section,
                    budget.spent,
                    int((time.monotonic() - started) * 1000),
                )
                raise
            # A rejected request is not going to be accepted on the second
            # attempt, and the call budget is 3 total -- spending them on one
            # provably-doomed request means never getting a reply at all.
            from .llm import is_retryable_status

            status = getattr(exc, "status_code", None)
            if status is not None and not is_retryable_status(status):
                raise
            last_error = str(exc)
            if attempt == 1:
                raise
            continue
        finally:
            # One line per attempt. llm.ok records the transport time of a single
            # provider call; this records how long the dialog has now been open,
            # which is the wait the person actually experiences and the only
            # number that explains an 80-second stall.
            logger.info(
                "assist.attempt section=%s attempt=%d attempt_ms=%d total_ms=%d",
                section,
                attempt + 1,
                int((time.monotonic() - attempt_started) * 1000),
                int((time.monotonic() - started) * 1000),
            )

        # Bookkeeping first: the numbers shown to the user must be the ones we
        # kept, not the ones the model claimed.
        _sanitise_fact_ids(result.bullets, len(facts))
        result.numbered_facts = facts
        result.unused_facts = unused_facts(facts, result.bullets)
        result.shared_facts = shared_facts(facts, result.bullets)

        # Run production guards
        texts = result.texts
        all_bullets = "\n".join(texts)
        guard_problems = fact_guard(all_bullets, source)
        banned = banned_phrases_found(all_bullets)
        reused = reused_metrics(texts)
        result.reused_metrics = reused

        if banned:
            # Retry once treating banned phrases as a parse failure
            if attempt == 0:
                prompt += f"\n\nWARNING: Your output contained banned phrases: {banned}. Remove them and rewrite."
                continue
            # Second attempt also has banned phrases — return with warning flag
            # (caller decides to show warning, not error)
            logger.warning("banned phrases still present after retry: %s", banned)

        if reused and attempt == 0:
            prompt += (
                f"\n\nWARNING: These metrics appear in more than one bullet: {reused}. "
                "Each metric may be used by at most one bullet. Rewrite so every "
                "figure is spent once, or drop the duplicate."
            )
            continue
        if reused:
            logger.warning("metric reused after retry: %s", reused)

        if guard_problems:
            if attempt == 0:
                prompt += f"\n\nWARNING: Fact guard failed: {guard_problems}. Do not invent the missing facts."
                continue
            # Second attempt — log and return anyway (caller shows warning)
            logger.warning("fact guard failed after retry: %s", guard_problems)

        logger.info(
            "assist.done section=%s bullets=%d calls=%d total_ms=%d",
            section,
            len(result.bullets),
            attempt + 1,
            int((time.monotonic() - started) * 1000),
        )
        return result

    raise RuntimeError(f"write_bullets failed after retry: {last_error}")


def _load_prompt(name: str) -> str:
    """Load a prompt file from the prompts/ directory."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "prompts"
    path = root / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")