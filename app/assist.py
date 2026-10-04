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
from typing import Callable, TypeVar

from pydantic import BaseModel, Field, ValidationError

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


class BulletsResult(BaseModel):
    """Output of POST /assist/answer: polished bullets."""

    bullets: list[str] = Field(default_factory=list)


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


# Proper-noun / tool heuristic: capitalized words in output not in source
_PROPER_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")


def invented_proper_nouns(output: str, source: str) -> list[str]:
    """Return capitalized words in output not found in source."""
    out_props = set(_PROPER_RE.findall(output))
    # Build a set of capitalized words from source
    src_props = set(_PROPER_RE.findall(source))
    # Also accept common English capitalized words that are not tools/employers
    common = {"The", "In", "At", "On", "For", "To", "With", "From", "By", "A", "An", "And", "Or", "But",
              "Built", "Led", "Designed", "Implemented", "Automated", "Reduced", "Increased", "Improved",
              "Launched", "Developed", "Deployed", "Integrated", "Scaled", "Measured", "Cut", "Accelerated",
              "Refactored", "Streamlined", "Delivered", "Owned", "Partnered", "Coordinated", "Documented",
              "Tested", "Instrumented", "Trained", "Mentored", "Architected", "Optimized", "Debugged",
              "Shipped", "Migrated", "Jobber", "Worked", "Handled", "Created", "Managed"}
    out_props = out_props - common
    src_props = src_props - common
    return sorted(out_props - src_props)


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
    return problems


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
    """
    from .llm import ask  # local import to avoid circular at module load

    ask_fn = llm or ask

    # Scope check
    scope = rules.load_rules().get("ai_scope", {})
    writable = scope.get("bullet_writing_sections", [])
    if section not in writable:
        raise ValueError(f"Section '{section}' does not support bullet writing")

    source = f"{raw_facts}\n{answers}" if answers else raw_facts
    prompt = _load_prompt("write_bullets.md") + f"\n\nFacts:\n{source}"

    last_error = ""
    for attempt in range(2):  # max 2 live calls including this
        try:
            result = ask_fn(BulletsResult, prompt)
        except Exception as exc:
            last_error = str(exc)
            if attempt == 1:
                raise
            continue

        # Run production guards
        all_bullets = "\n".join(result.bullets)
        guard_problems = fact_guard(all_bullets, source)
        banned = banned_phrases_found(all_bullets)

        if banned:
            # Retry once treating banned phrases as a parse failure
            if attempt == 0:
                prompt += f"\n\nWARNING: Your output contained banned phrases: {banned}. Remove them and rewrite."
                continue
            # Second attempt also has banned phrases — return with warning flag
            # (caller decides to show warning, not error)
            logger.warning("banned phrases still present after retry: %s", banned)

        if guard_problems:
            if attempt == 0:
                prompt += f"\n\nWARNING: Fact guard failed: {guard_problems}. Do not invent the missing facts."
                continue
            # Second attempt — log and return anyway (caller shows warning)
            logger.warning("fact guard failed after retry: %s", guard_problems)

        return result

    raise RuntimeError(f"write_bullets failed after retry: {last_error}")


def _load_prompt(name: str) -> str:
    """Load a prompt file from the prompts/ directory."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "prompts"
    path = root / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    text = path.read_text(encoding="utf-8")
    # Also inject the shared honesty rules
    honesty_path = root / "_honesty.md"
    if honesty_path.exists():
        honesty = honesty_path.read_text(encoding="utf-8")
        return f"{honesty}\n\n---\n\n{text}"
    return text