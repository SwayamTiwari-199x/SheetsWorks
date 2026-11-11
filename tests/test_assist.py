"""assist.py: section-scoped AI assist, robust JSON extraction, fact guard, banned phrases.

All LLM calls are mocked via the injectable ``llm=`` parameter. No network.
"""

from __future__ import annotations

import json
import re

import pytest

from app.assist import (
    BulletsResult,
    ExtractResult,
    SuggestedBullet,
    ai_tells_found,
    ask_clarifying,
    banned_phrases_found,
    extract_schema_json,
    fact_guard,
    invented_digits,
    invented_mechanisms,
    invented_number_words,
    invented_percents,
    invented_proper_nouns,
    metric_keys,
    reused_metrics,
    shared_facts,
    split_facts,
    unused_facts,
    write_bullets,
)
from pydantic import BaseModel, Field


# --- helpers ---------------------------------------------------------------


def fake_ask(responses: list) -> callable:
    """Return a fake ask() that pops from responses, parsing JSON each call.

    A stand-in for `app.llm.ask`, so it takes the same keyword arguments. That
    matters: `write_bullets` hands every call the one `CallBudget` for the press,
    and a fake that refused the keyword would not be measuring the thing the
    budget exists to bound.
    """
    idx = 0

    def _ask(schema: type[BaseModel], prompt: str, **kw) -> BaseModel:
        nonlocal idx
        budget = kw.get("budget")
        if budget is not None:
            budget.take()
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


# --- the guard must not read a capital letter as a proper noun --------------
# These are the exact three words the one live run got wrong. All three open a
# sentence, which is why the guard flagged them, and the retry it spent on that
# false positive produced a reply no better than the first.


@pytest.mark.parametrize("word", ["Collaborated", "Helped", "Served"])
def test_a_capitalised_opening_verb_is_not_a_proper_noun(word: str) -> None:
    source = "worked on the billing service for 120 recruiters"
    output = f"{word} the billing team to cut page load from 2s to 400ms"
    assert invented_proper_nouns(output, source) == [], output
    assert not any("proper noun" in p for p in fact_guard(output, source))


def test_the_first_word_of_a_bullet_is_never_a_proper_noun() -> None:
    """Position, not vocabulary. Any sentence-initial capital is grammatical."""
    source = "cut page load from 2s to 400ms on a FastAPI and Postgres backend"
    for opener in ("Reduced", "Instrumented", "Migrated", "Benchmarked",
                   "Streamlined", "Debugged", "Partnered"):
        output = f"{opener} page load from 2s to 400ms using FastAPI"
        assert invented_proper_nouns(output, source) == [], output


def test_a_capitalised_word_after_a_clause_boundary_is_still_checked() -> None:
    """Sentence-initial is exempt. Mid-sentence is where a tool would appear.

    The exemption is positional, so a tool named after a comma is still caught.
    """
    source = "worked on the payments service"
    output = "Worked on the payments service, using Kafka"
    assert invented_proper_nouns(output, source) == ["Kafka"]


def test_a_tool_the_user_typed_lowercase_is_not_invented() -> None:
    """"redis" in the input is Redis named, not an invention."""
    source = "used redis on the payment path, page load 2s -> 400ms"
    output = "Cut page load from 2s to 400ms using Redis on the payment path"
    assert invented_proper_nouns(output, source) == [], output


def test_a_capitalised_tool_the_user_never_typed_is_still_caught() -> None:
    """The position exemption must not become a blanket pass."""
    source = "used FastAPI and Postgres for the billing service"
    output = "Built the billing service with FastAPI, Postgres and Kubernetes"
    assert invented_proper_nouns(output, source) == ["Kubernetes"]


def test_a_midsentence_ordinary_word_the_user_never_typed_is_not_caught() -> None:
    """The allowlist covers the common ones so the guard does not fire on noise."""
    source = "page load 2s -> 400ms on the payments service"
    output = "Reduced page load from 2s to 400ms, saving 160ms per request"
    assert invented_proper_nouns(output, source) == [], output


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


# --- fact splitting, with the exact input that failed live ----------------

# Verbatim from the one live run that produced overlapping facts: the raw dump
# the user typed, then the answers block restating two of the same lines under
# the numbering the questions used.
LIVE_RAW = (
    "worked on backend for a staffing app using FastAPI and Postgres\n"
    "1. 120 recruiters\n"
    "2. FastAPI, Postgres, Redis\n"
    "3. cut page load from 2s to 400ms\n"
    "4. my part, small team of 3"
)
LIVE_ANSWERS = (
    "1. my part was the billing service\n"
    "2. cut page load from 2s to 400ms"
)


def test_a_restated_line_is_not_a_second_fact() -> None:
    """Seven lines, six claims.

    The answers block answered question 2 by pasting the same words the user had
    already typed. Numbering both gave two ids for one claim, and the model cited
    both on different bullets -- which is how two near-identical bullets got
    written from one piece of work.
    """
    source = LIVE_RAW + "\n" + LIVE_ANSWERS
    assert len(source.splitlines()) == 7
    facts = split_facts(source)
    assert len(facts) == 6, facts
    assert len(facts) == len(set(facts)), facts
    joined = " ".join(facts).lower()
    assert joined.count("cut page load from 2s to 400ms") == 1, facts


def test_the_users_own_numbering_is_stripped_from_the_fact_text() -> None:
    """The number printed in the fact text was not the id the model had to cite.

    Fact 4 read "1. 120 recruiters", so the model saw a 1 where it should have
    seen a 4, and the ids it returned drifted away from the list it was shown.
    """
    for fact in split_facts(LIVE_RAW + "\n" + LIVE_ANSWERS):
        assert not re.match(r"^\(?\d{1,2}[.)]\s", fact), fact
    assert "120 recruiters" in split_facts(LIVE_RAW + "\n" + LIVE_ANSWERS)


def test_distinct_lines_are_still_distinct_facts() -> None:
    """Merging must not swallow a genuinely new answer.

    "my part was the billing service" shares two words with "my part, small team
    of 3" and adds three. That is a new claim, and losing it would silently drop
    something the user just typed.
    """
    facts = split_facts(LIVE_RAW + "\n" + LIVE_ANSWERS)
    assert "120 recruiters" in facts
    assert "my part, small team of 3" in facts
    assert "my part was the billing service" in facts
    assert "FastAPI, Postgres, Redis" in facts


def test_a_longer_restatement_replaces_the_shorter_one() -> None:
    """The wording with more in it wins, so nothing the user typed is lost."""
    facts = split_facts("cut page load\ncut page load from 2s to 400ms")
    assert facts == ["cut page load from 2s to 400ms"]


def test_two_bullets_on_one_claim_are_reported() -> None:
    """The exact citation pattern the live run produced."""
    facts = split_facts(LIVE_RAW + "\n" + LIVE_ANSWERS)
    bullets = [
        SuggestedBullet(text="Developed the billing service for the app.", facts=[1, 5]),
        SuggestedBullet(text="Built the app's backend end to end.", facts=[1, 3]),
    ]
    assert shared_facts(facts, bullets) == [1]


def test_two_bullets_may_share_a_bare_figure() -> None:
    """Sharing context is not sharing a claim.

    "120 recruiters" is a number the user supplied, not something they did. Two
    different claims can both be measured against it; two claims cannot both be
    "I owned the billing service".
    """
    facts = split_facts("120 recruiters\nowned the billing service")
    bullets = [
        SuggestedBullet(text="Cut page load from 2s to 400ms.", facts=[1, 2]),
        SuggestedBullet(text="Served the recruiter base.", facts=[1]),
    ]
    assert shared_facts(facts, bullets) == []


def test_a_shared_fact_id_outside_the_list_is_not_reported() -> None:
    """Ids are sanitised before this runs, but the guard must not trust that."""
    facts = split_facts("one thing\nanother thing")
    bullets = [SuggestedBullet(text="a", facts=[1, 99]),
               SuggestedBullet(text="b", facts=[1, 99])]
    assert shared_facts(facts, bullets) == [1]


# --- write_bullets -------------------------------------------------------


def test_write_bullets_happy_path() -> None:
    fake = fake_ask([
        BulletsResult(bullets=["Built X using Y, cutting Z from A to B"])
    ])
    result = write_bullets("experience", "Built X using Y, cutting Z from A to B", llm=fake)
    assert result.texts == ["Built X using Y, cutting Z from A to B"]


def test_a_rejected_request_is_not_retried_into_the_live_budget() -> None:
    """The bug behind the user's 400: one rejected request consumed both live
    calls and still reported nothing useful. A 4xx that is not 429 must go
    straight out."""
    from app.llm import LLMError

    calls = []

    def reject(schema, prompt, **kw):
        calls.append(prompt)
        raise LLMError("HTTP 400 from openrouter", provider="openrouter",
                       model="m", detail="max_tokens must be less than 1",
                       status_code=400)

    with pytest.raises(LLMError) as excinfo:
        write_bullets("experience", "cut load from 2s to 400ms", llm=reject)
    assert excinfo.value.status_code == 400
    assert calls == [] or len(calls) == 1, f"spent {len(calls)} calls on a 400"


def test_a_429_does_retry_because_it_means_not_now() -> None:
    from app.llm import LLMError

    seen = []

    def throttled(schema, prompt, **kw):
        seen.append(prompt)
        if len(seen) == 1:
            raise LLMError("HTTP 429 from openrouter", provider="openrouter",
                           model="m", detail="rate limited", status_code=429)
        return BulletsResult(bullets=["Cut page load from 2s to 400ms"])

    result = write_bullets("experience", "cut page load from 2s to 400ms",
                           llm=throttled)
    assert len(seen) == 2
    assert result.texts == ["Cut page load from 2s to 400ms"]


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
    assert "Results-driven" not in result.texts[0]


def test_write_bullets_detects_invented_digit_and_retries() -> None:
    """Fact guard catches invented digit; retry with warning."""
    fake = fake_ask([
        BulletsResult(bullets=["Handled 500 requests/sec"]),
        BulletsResult(bullets=["Handled high request volume"]),
    ])
    result = write_bullets("experience", "handled requests", llm=fake)
    # The second (retried) result should be returned
    assert result.texts == ["Handled high request volume"]


def test_write_bullets_fact_guard_allows_present_digits() -> None:
    """Digits present in source are allowed."""
    fake = fake_ask([
        BulletsResult(bullets=["Handled 500 requests/sec"])
    ])
    result = write_bullets("experience", "handled 500 requests/sec", llm=fake)
    assert result.texts == ["Handled 500 requests/sec"]


# --- mechanism watchlist: "using Redis" is not "Redis caching" -------------


def test_the_watchlist_catches_redis_caching_when_the_user_never_said_it() -> None:
    """The exact case: Redis is a listed tool, a page-load figure is given, and
    the writer attaches "caching" to Redis anyway."""
    source = (
        "worked on backend for a staffing app using FastAPI and Postgres\n"
        "1. 120 recruiters\n"
        "2. FastAPI, Postgres, Redis\n"
        "3. cut page load from 2s to 400ms\n"
        "4. my part, small team of 3"
    )
    output = "Optimized API performance with Redis caching, cutting page load from 2s to 400ms"
    assert invented_mechanisms(output, source) == ["caching"]
    assert any("mechanism" in p for p in fact_guard(output, source))


def test_the_watchlist_allows_a_mechanism_the_user_did_say() -> None:
    source = "used Redis caching on the payment path, page load 2s -> 400ms"
    output = "Cut page load from 2s to 400ms using Redis caching"
    assert invented_mechanisms(output, source) == []


@pytest.mark.parametrize("word", [
    "caching", "indexed", "async", "queued", "load balanced",
    "sharded", "replicated", "batched", "pooling", "throttled",
])
def test_the_watchlist_covers_the_common_mechanism_words(word: str) -> None:
    source = "worked on the payments service, page load 2s -> 400ms"
    output = f"Improved the payments service ({word}), page load 2s -> 400ms"
    assert invented_mechanisms(output, source)


def test_write_bullets_retries_when_the_writer_invents_a_mechanism() -> None:
    """The guard runs in production, not just in a unit test of the guard."""
    fake = fake_ask([
        BulletsResult(bullets=[SuggestedBullet(
            text="Optimized API performance with Redis caching, cutting page load from 2s to 400ms",
            facts=[1, 3])]),
        BulletsResult(bullets=[SuggestedBullet(
            text="Cut page load from 2s to 400ms on a FastAPI and Postgres backend",
            facts=[1, 3])]),
    ])
    result = write_bullets(
        "experience",
        "worked on backend for a staffing app using FastAPI and Postgres\n"
        "1. 120 recruiters\n"
        "2. FastAPI, Postgres, Redis\n"
        "3. cut page load from 2s to 400ms\n"
        "4. my part, small team of 3",
        llm=fake,
    )
    assert "caching" not in result.texts[0]
    assert "Redis caching" not in result.texts[0]


# --- fact bookkeeping: which facts each bullet uses -----------------------


def test_facts_are_numbered_one_per_line() -> None:
    """The user's own list marker is dropped; ours is the only numbering.

    This asserted the marker survived, which was the bug: the model was shown
    "1. 120 recruiters" as fact 2 and had no way to tell that fact from the "1"
    the list itself printed.
    """
    source = "worked on the backend\n1. 120 recruiters\n2. team of 3"
    assert split_facts(source) == [
        "worked on the backend", "120 recruiters", "team of 3",
    ]


@pytest.mark.parametrize("marker", ["1.", "1)", "-", "*", "\u2022"])
def test_every_list_marker_is_stripped(marker: str) -> None:
    facts = split_facts(f"{marker} one claim\n{marker} another claim")
    assert facts == ["one claim", "another claim"], facts


def test_each_bullet_reports_the_facts_it_uses() -> None:
    fake = fake_ask([
        BulletsResult(bullets=[
            SuggestedBullet(text="Built the backend for 120 recruiters", facts=[1, 2]),
            SuggestedBullet(text="Worked as one of 3 engineers", facts=[3]),
        ])
    ])
    result = write_bullets(
        "experience",
        "worked on the backend\n1. 120 recruiters\n2. FastAPI\n3. small team of 3",
        llm=fake,
    )
    assert result.bullets[0].facts == [1, 2]
    assert result.bullets[1].facts == [3]
    assert result.numbered_facts == [
        "worked on the backend", "120 recruiters", "FastAPI", "small team of 3",
    ]


def test_an_unused_fact_is_reported() -> None:
    """The team-of-3 fact the bullets never used must be named, not dropped.

    This is the case where the earlier writer output said "my part, small team
    of 3" appeared in no bullet and nothing in the UI said so.
    """
    fake = fake_ask([
        BulletsResult(bullets=[
            SuggestedBullet(text="Built the FastAPI backend for 120 recruiters", facts=[1, 2, 3]),
        ])
    ])
    result = write_bullets(
        "experience",
        "worked on the backend\n1. 120 recruiters\n2. FastAPI\n3. my part, small team of 3",
        llm=fake,
    )
    # Facts are numbered 1..4 over the four lines above; only line 4 is unused.
    assert result.unused_facts == [4]
    assert result.numbered_facts[3] == "my part, small team of 3"


def test_two_bullets_resting_on_one_claim_are_reported_by_write_bullets() -> None:
    """The rule reaches the response body, not just the helper."""
    fake = fake_ask([
        BulletsResult(bullets=[
            SuggestedBullet(text="Built the backend for 120 recruiters", facts=[1, 3]),
            SuggestedBullet(text="Worked on the backend with a small team of 3", facts=[1, 4]),
        ])
    ])
    result = write_bullets(
        "experience",
        "worked on the backend\nowned the billing service\n120 recruiters\nsmall team of 3",
        llm=fake,
    )
    assert result.shared_facts == [1]


def test_a_fact_id_the_model_invented_is_dropped() -> None:
    """A label pointing at a fact the user never gave is worse than no label."""
    fake = fake_ask([
        BulletsResult(bullets=[SuggestedBullet(text="Built the backend", facts=[1, 99])])
    ])
    result = write_bullets("experience", "worked on the backend", llm=fake)
    assert result.bullets[0].facts == [1]
    assert 99 not in result.bullets[0].facts


# --- one metric per bullet -------------------------------------------------


def test_metric_keys_canonicalise_the_unit() -> None:
    """2 seconds and 2s are the same figure, so they are the same metric."""
    assert metric_keys("cut page load from 2 seconds to 400 milliseconds") == {"2s", "400ms"}
    assert metric_keys("cut page load from 2s to 400ms") == {"2s", "400ms"}


def test_two_bullets_may_not_reuse_the_same_metric() -> None:
    assert reused_metrics([
        "Cut page load from 2s to 400ms with FastAPI and Postgres",
        "Served 120 recruiters on a FastAPI and Postgres backend",
    ]) == []
    assert reused_metrics([
        "Cut page load from 2s to 400ms on the FastAPI backend",
        "Reduced page load from 2 seconds to 400 milliseconds",
    ]) == ["2s", "400ms"]


def test_write_bullets_retries_when_a_metric_is_reused() -> None:
    fake = fake_ask([
        BulletsResult(bullets=[
            SuggestedBullet(text="Cut page load from 2s to 400ms", facts=[3]),
            SuggestedBullet(text="Reduced page load from 2 seconds to 400 milliseconds", facts=[3]),
        ]),
        BulletsResult(bullets=[
            SuggestedBullet(text="Cut page load from 2s to 400ms", facts=[3]),
            SuggestedBullet(text="Worked on a small team of 3 engineers", facts=[4]),
        ]),
    ])
    result = write_bullets(
        "experience",
        "worked on the backend\n3. cut page load from 2s to 400ms\n4. my part, small team of 3",
        llm=fake,
    )
    assert result.reused_metrics == []
    assert result.texts == [
        "Cut page load from 2s to 400ms",
        "Worked on a small team of 3 engineers",
    ]


def test_a_reused_metric_is_reported_when_the_retry_still_repeats_it() -> None:
    """One retry, then a visible warning rather than a hard failure."""
    same = [
        SuggestedBullet(text="Cut page load from 2s to 400ms", facts=[3]),
        SuggestedBullet(text="Reduced page load from 2 seconds to 400 milliseconds", facts=[3]),
    ]
    fake = fake_ask([BulletsResult(bullets=same)])
    result = write_bullets(
        "experience",
        "worked on the backend\n3. cut page load from 2s to 400ms",
        llm=fake,
    )
    assert result.reused_metrics == ["2s", "400ms"]


def test_unused_facts_helper_ignores_facts_no_bullet_claims() -> None:
    numbered = ["a", "b", "c"]
    bullets = [SuggestedBullet(text="x", facts=[1]), SuggestedBullet(text="y", facts=[2, 2])]
    assert unused_facts(numbered, bullets) == [3]


# --- the result survives a model that returns a bare list -------------------


def test_a_bare_list_of_bullets_is_accepted() -> None:
    fake = fake_ask(['["Cut page load from 2s to 400ms"]'])
    result = write_bullets("experience", "cut page load from 2s to 400ms", llm=fake)
    assert result.texts == ["Cut page load from 2s to 400ms"]
    assert result.bullets[0].facts == []


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
        print(f"  - {b.text}")
        print(f"      uses facts {b.facts}")
    print(f"Unused facts: {bullets.unused_facts}")
    for i in bullets.unused_facts:
        print(f"  ! fact {i} unused: {bullets.numbered_facts[i - 1]}")
    print(f"Reused metrics: {bullets.reused_metrics}")

    # Acceptance 2: bullet must contain ONLY numbers from raw_facts
    import re
    all_text = "\n".join(bullets.texts)
    numbers_in_output = set(re.findall(r"\d+", all_text))
    numbers_in_input = set(re.findall(r"\d+", raw_facts))
    invented = numbers_in_output - numbers_in_input
    print(f"\nNumbers in output: {numbers_in_output}")
    print(f"Numbers in input:  {numbers_in_input}")
    print(f"Invented:          {invented}")
    assert not invented, f"Acceptance 2 failed: invented numbers {invented}"
    print(f"\nTOTAL LIVE CALLS: {calls}")


@pytest.mark.live
def test_live_acceptance_3_vague_input_returns_questions() -> None:
    """Acceptance 3: vague input returns clarifying questions, not invented
    bullets. Runs against the real provider.
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

    from app.assist import ask_clarifying

    prompt = "did stuff with the backend, it was good"
    result = ask_clarifying("experience", prompt)
    print(f"\n--- ACCEPTANCE 3 ---")
    print(f"Input:  {prompt}")
    print(f"Questions: {result.questions}")
    print(f"Entries: {result.entries}")
    assert result.questions, "Acceptance 3 failed: vague input must return questions, not empty"

