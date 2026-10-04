"""assist.py: section-scoped AI assist, robust JSON extraction, fact guard, banned phrases.

All LLM calls are mocked via the injectable ``llm=`` parameter. No network.
"""

from __future__ import annotations

import json

import pytest

from app.assist import (
    BulletsResult,
    ExtractResult,
    ai_tells_found,
    ask_clarifying,
    banned_phrases_found,
    extract_schema_json,
    fact_guard,
    invented_digits,
    invented_number_words,
    invented_percents,
    invented_proper_nouns,
    write_bullets,
)
from pydantic import BaseModel, Field


# --- helpers ---------------------------------------------------------------


def fake_ask(responses: list) -> callable:
    """Return a fake ask() that pops from responses, parsing JSON each call."""
    idx = 0

    def _ask(schema: type[BaseModel], prompt: str) -> BaseModel:
        nonlocal idx
        i = min(idx, len(responses) - 1)
        idx += 1
        raw = responses[i]
        if isinstance(raw, str):
            try:
                return schema.model_validate_json(raw)
            except Exception:
                # Try as list for BulletsResult
                if raw.strip().startswith("["):
                    return schema.model_validate(json.loads(raw))
                raise
        return raw  # already a BaseModel instance

    return _ask


# --- robust JSON extraction -----------------------------------------------


class _Obj(BaseModel):
    answer: str  # required, no default — so {"analysis": "..."} fails validation


def test_extract_schema_json_whole() -> None:
    out = extract_schema_json('{"answer": "hi"}', _Obj)
    assert out.answer == "hi"


def test_extract_schema_json_fenced() -> None:
    out = extract_schema_json('Sure!```json\n{"answer": "hi"}\n```', _Obj)
    assert out.answer == "hi"


def test_extract_schema_json_reasoning_around() -> None:
    text = (
        'Let me think... The key insight is that...\n'
        'Here is the result:\n'
        '{"answer": "hi"}\n'
        'I hope that helps!'
    )
    out = extract_schema_json(text, _Obj)
    assert out.answer == "hi"


def test_extract_schema_json_multiple_objects() -> None:
    text = '{"analysis": "..."} then the answer: {"answer": "yes"}'
    out = extract_schema_json(text, _Obj)
    assert out.answer == "yes"


def test_extract_schema_json_validation() -> None:
    """A JSON object that does not match the schema is skipped."""
    text = '{"wrong": 123} then {"answer": "correct"}'
    out = extract_schema_json(text, _Obj)
    assert out.answer == "correct"


# --- fact guard -----------------------------------------------------------


def test_fact_guard_no_invented_digits() -> None:
    source = "worked on ads for a staffing app using FastAPI and Postgres"
    output = "Built a staffing app backend using FastAPI and Postgres"
    assert invented_digits(output, source) == []


def test_fact_guard_catches_invented_digit() -> None:
    source = "worked on ads for a staffing app"
    output = "Built a staffing app handling 500 requests/sec"
    assert invented_digits(output, source) == ["500"]


def test_fact_guard_catches_invented_number_word() -> None:
    source = "worked on backend"
    output = "Built a backend for three microservices"
    assert invented_number_words(output, source) == ["three"]


def test_fact_guard_catches_invented_percent() -> None:
    source = "improved performance"
    output = "Improved performance by 50%"
    assert invented_percents(output, source) == ["50%"]


def test_fact_guard_catches_invented_proper_noun() -> None:
    source = "built a web app"
    output = "Built a web app using React and Python"
    assert invented_proper_nouns(output, source) == ["Python", "React"]


def test_fact_guard_empty_when_all_present() -> None:
    source = "used FastAPI, Postgres, handled 100 users, 99% uptime"
    output = "Built API with FastAPI and Postgres handling 100 users at 99% uptime"
    assert fact_guard(output, source) == []


# --- banned phrases & AI tells --------------------------------------------


def test_banned_phrases_found() -> None:
    text = "Results-driven team player. Detail-oriented."
    found = banned_phrases_found(text)
    assert "results-driven" in found
    assert "team player" in found
    assert "detail-oriented" in found


def test_banned_phrases_clean() -> None:
    text = "Built a pipeline reducing latency by 40%"
    assert banned_phrases_found(text) == []


def test_ai_tells_found() -> None:
    text = "Leveraged cutting-edge technology seamlessly."
    found = ai_tells_found(text)
    assert "leveraged" in found
    assert "cutting-edge" in found
    assert "seamlessly" in found


def test_ai_tells_clean() -> None:
    text = "Built a pipeline reducing latency by 40%"
    assert ai_tells_found(text) == []


# --- ask_clarifying -------------------------------------------------------


def test_ask_clarifying_experience_returns_questions() -> None:
    fake = fake_ask([
        ExtractResult(
            entries=[{"org": "Acme", "role": "Dev", "bullets": ["worked on backend"]}],
            questions=["How many users?", "What stack?"],
        )
    ])
    result = ask_clarifying("experience", "worked on backend at Acme", llm=fake)
    assert len(result.entries) == 1
    assert result.questions == ["How many users?", "What stack?"]


def test_ask_clarifying_education_structure_only() -> None:
    """Education is structure_only: no questions, just extraction."""
    fake = fake_ask([
        ExtractResult(
            entries=[{"org": "MIT", "role": "", "bullets": []}],
            questions=[],
        )
    ])
    result = ask_clarifying("education", "MIT 2020-2024", llm=fake)
    assert result.questions == []
    assert result.entries[0].org == "MIT"


def test_ask_clarifying_unsupported_section() -> None:
    with pytest.raises(ValueError, match="not supported"):
        ask_clarifying("summary", "x", llm=fake_ask([]))


# --- write_bullets -------------------------------------------------------


def test_write_bullets_happy_path() -> None:
    fake = fake_ask([
        BulletsResult(bullets=["Built X using Y, cutting Z from A to B"])
    ])
    result = write_bullets("experience", "Built X using Y, cutting Z from A to B", llm=fake)
    assert result.bullets == ["Built X using Y, cutting Z from A to B"]


def test_write_bullets_education_rejected() -> None:
    """Education does not support bullet writing."""
    with pytest.raises(ValueError, match="does not support"):
        write_bullets("education", "MIT 2020", llm=fake_ask([]))


def test_write_bullets_detects_banned_phrase_and_retries() -> None:
    """Banned phrase in first attempt triggers retry; second attempt OK."""
    fake = fake_ask([
        BulletsResult(bullets=["Results-driven team player built stuff"]),
        BulletsResult(bullets=["Built a system reducing latency by 40%"]),
    ])
    result = write_bullets("experience", "built system, reduced latency 40%", llm=fake)
    assert "Results-driven" not in result.bullets[0]


def test_write_bullets_detects_invented_digit_and_retries() -> None:
    """Fact guard catches invented digit; retry with warning."""
    fake = fake_ask([
        BulletsResult(bullets=["Handled 500 requests/sec"]),
        BulletsResult(bullets=["Handled high request volume"]),
    ])
    result = write_bullets("experience", "handled requests", llm=fake)
    # The second (retried) result should be returned
    assert result.bullets == ["Handled high request volume"]


def test_write_bullets_fact_guard_allows_present_digits() -> None:
    """Digits present in source are allowed."""
    fake = fake_ask([
        BulletsResult(bullets=["Handled 500 requests/sec"])
    ])
    result = write_bullets("experience", "handled 500 requests/sec", llm=fake)
    assert result.bullets == ["Handled 500 requests/sec"]


@pytest.mark.live
def test_live_acceptance_1_and_2() -> None:
    """Acceptance criteria 1+2 from Stage 4, hitting the real provider.

    Acceptance 1: free text like 'worked on backend for a staffing app using
    FastAPI and Postgres' makes the AI ask clarifying questions rather than
    inventing numbers.
    Acceptance 2: after I supply numbers, the bullet contains only those
    numbers.

    Uses app.llm.ask directly (no TestClient), so this is exactly 2 live
    calls: one for extraction+questions, one for bullet writing.
    """
    import os
    if not os.getenv("RUN_LIVE_LLM"):
        pytest.skip("set RUN_LIVE_LLM=1 to run")

    # Restore the real key from .env for this live test only.
    # conftest scrubs OPENROUTER_API_KEY from the process env to prevent leaks;
    # live tests deliberately opt back in.
    from pathlib import Path
    env_text = Path(".env").read_text(encoding="utf-8")
    for line in env_text.splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            key = line.split("=", 1)[1].strip()
            os.environ["OPENROUTER_API_KEY"] = key
            break

    from app import config
    config.get_settings.cache_clear()

    from app.assist import ask_clarifying, write_bullets

    calls = 0
    # Call 1: extract + questions
    free_text = "worked on backend for a staffing app using FastAPI and Postgres"
    extract = ask_clarifying("experience", free_text)
    calls += 1
    print(f"\n--- LIVE CALL {calls} (extract/questions) ---")
    print(f"Entries: {extract.entries}")
    print(f"Questions: {extract.questions}")
    assert extract.questions, "Acceptance 1: must ask clarifying questions"

    # Supply the numbers the user said
    answers = "1. 120 recruiters\n2. FastAPI, Postgres, Redis\n3. cut page load from 2s to 400ms\n4. my part, small team of 3"

    # Call 2: write bullets
    raw_facts = free_text + "\n" + answers
    bullets = write_bullets("experience", raw_facts)
    calls += 1
    print(f"\n--- LIVE CALL {calls} (write_bullets) ---")
    for b in bullets.bullets:
        print(f"  - {b}")

    # Acceptance 2: bullet must contain ONLY numbers from raw_facts
    import re
    all_text = "\n".join(bullets.bullets)
    numbers_in_output = set(re.findall(r"\d+", all_text))
    numbers_in_input = set(re.findall(r"\d+", raw_facts))
    invented = numbers_in_output - numbers_in_input
    print(f"\nNumbers in output: {numbers_in_output}")
    print(f"Numbers in input:  {numbers_in_input}")
    print(f"Invented:          {invented}")
    assert not invented, f"Acceptance 2 failed: invented numbers {invented}"
    print(f"\nTOTAL LIVE CALLS: {calls}")


@pytest.mark.live
def test_live_acceptance_3_fact_guard() -> None:
    """Acceptance 3: feed a prompt that tempts invention; output contains no
    digits not in the input. Runs with the production fact_guard, not the LLM's
    opinion.
    """
    import os
    if not os.getenv("RUN_LIVE_LLM"):
        pytest.skip("set RUN_LIVE_LLM=1 to run")

    # Restore the real key from .env for this live test only.
    from pathlib import Path
    env_text = Path(".env").read_text(encoding="utf-8")
    for line in env_text.splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            key = line.split("=", 1)[1].strip()
            os.environ["OPENROUTER_API_KEY"] = key
            break

    from app import config
    config.get_settings.cache_clear()

    from app.assist import fact_guard, write_bullets

    prompt = "did stuff with the backend, it was good"
    result = write_bullets("experience", prompt)
    output = "\n".join(result.bullets)
    problems = fact_guard(output, prompt)
    print(f"\n--- ACCEPTANCE 3 ---")
    print(f"Input:  {prompt}")
    print(f"Output: {output}")
    print(f"Fact guard: {problems or 'clean'}")
    assert not any("invented digits" in p for p in problems), "Acceptance 3 failed"

