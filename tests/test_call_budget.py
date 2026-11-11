"""One provider-call budget per button press, shared by llm.ask and
assist.write_bullets.

Two layers of retry used to keep separate counters: `llm.ask` would spend up to
MAX_ATTEMPTS provider calls, and `write_bullets` would then run the whole call
again. Neither could see the other's spending, so the worst case was the
product of the two and growing one budget quietly doubled the other.

This drives the real `ask` against a fake client that never succeeds, and
counts the HTTP requests. No network, no key, no live calls.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.llm import (
    MAX_CALLS_PER_PRESS,
    CallBudget,
    CallBudgetExhausted,
    LLMError,
    ask,
)

from .fakes import FakeClient

MODEL = "test-vendor/test-model:free"


class Out:
    """Unused; the real schema is defined inside the tests that need one."""


def settings_for(provider: str = "openrouter", **kw) -> Settings:
    return Settings(llm_provider=provider, _env_file=None, llm_model=MODEL, **kw)


# --- the budget itself -----------------------------------------------------


def test_a_budget_allows_exactly_its_limit() -> None:
    budget = CallBudget(limit=3)
    assert [budget.take() for _ in range(3)] == [1, 2, 3]
    assert budget.spent == 3
    assert budget.remaining == 0


def test_the_fourth_call_is_refused_and_says_why() -> None:
    budget = CallBudget(limit=3)
    for _ in range(3):
        budget.take()
    with pytest.raises(CallBudgetExhausted) as exc:
        budget.take()
    message = str(exc.value)
    assert "3" in message, message
    # The two things a person needs: what happened, and what it cost them.
    assert "nothing was saved" in message.lower(), message
    assert "call" in message, message


def test_the_refusal_is_not_dressed_up_as_a_provider_failure() -> None:
    """It is deliberately not an LLMError. A spent budget is not something the
    provider did, and every `except LLMError` here renders the error as
    "[provider/model] HTTP 4xx: what the provider said" -- inventing both a
    culprit and a status code. `tests/test_assist_route.py` asserts the sentence
    survives both AI routes."""
    budget = CallBudget(limit=1)
    budget.take()
    with pytest.raises(CallBudgetExhausted) as exc:
        budget.take()
    assert not isinstance(exc.value, LLMError), type(exc.value).__mro__


def test_the_refusal_names_no_provider() -> None:
    """Nothing refused it. Naming a provider invents a culprit, and the
    rendering below would print one as "[provider/model]"."""
    budget = CallBudget(limit=1)
    budget.take()
    with pytest.raises(CallBudgetExhausted) as exc:
        budget.take()
    rendered = exc.value.report()
    assert "[" not in rendered, rendered
    assert str(exc.value) == rendered, (str(exc.value), rendered)


def test_the_budget_default_is_three() -> None:
    """Three, not four. The old combined worst case was 2 x 2 = 4 provider calls
    for one button press, and the product cap was 4, so there was no room left
    for anything."""
    assert CallBudget().limit == MAX_CALLS_PER_PRESS
    assert MAX_CALLS_PER_PRESS == 3


# --- the stub that always fails -------------------------------------------


def always_truncating() -> FakeClient:
    """A provider that accepts every request and answers with nothing, which is
    what makes `ask` raise the token limit and try again -- the case that spent
    the most calls before the budget existed."""
    return FakeClient(replies=[""], status_code=200)


def test_ask_alone_never_exceeds_the_budget() -> None:
    from pydantic import BaseModel

    class Out(BaseModel):
        answer: str

    client = always_truncating()
    with pytest.raises(LLMError):
        ask(Out, "hello", settings=settings_for(), client=client)
    assert client.call_count <= MAX_CALLS_PER_PRESS, client.call_count


def test_a_truncation_retry_costs_budget_too() -> None:
    """The raise-and-retry is a second live call. Exempting it is how a single
    button press turned into four."""
    from pydantic import BaseModel

    class Out(BaseModel):
        answer: str

    budget = CallBudget()
    client = always_truncating()
    with pytest.raises(LLMError):
        ask(Out, "hello", settings=settings_for(), client=client, budget=budget)
    assert budget.spent <= MAX_CALLS_PER_PRESS, budget.spent
    assert client.call_count == budget.spent, (client.call_count, budget.spent)


def test_write_bullets_never_exceeds_three_calls_when_the_model_never_answers() -> None:
    """The whole point: one button press, both retry layers, one counter.

    Driven through the real `llm.ask` so the shared counter is what is being
    measured rather than a fake that might not charge itself.
    """
    from app.assist import write_bullets

    fake_client = always_truncating()
    configured = settings_for()

    def real_ask(schema, prompt, *, settings=None, client=None, budget=None):
        assert budget is not None, "write_bullets did not pass a budget to ask"
        assert client is None, "write_bullets should not pass its own client"
        return ask(schema, prompt, settings=configured, client=fake_client,
                   budget=budget)

    with pytest.raises(Exception) as exc:
        write_bullets("experience", "cut page load from 2s to 400ms",
                      llm=real_ask)

    assert fake_client.call_count <= MAX_CALLS_PER_PRESS, (
        f"{fake_client.call_count} provider calls for one button press"
    )
    assert "nothing was saved" in str(exc.value).lower(), str(exc.value)


def test_the_budget_is_shared_not_merely_equal() -> None:
    """Two layers with the same limit each is not one budget. If the inner layer
    creates its own, an outer loop can still push the total past the cap."""
    from app.assist import write_bullets

    fake_client = always_truncating()
    charged: list[int] = []

    def ask_charging_budget(schema, prompt, *, settings=None, client=None,
                            budget=None):
        assert budget is not None, "write_bullets did not pass a budget to ask"
        before = budget.spent
        with pytest.raises(LLMError):
            ask(schema, prompt, settings=settings_for(), client=fake_client,
                budget=budget)
        charged.append(budget.spent - before)
        raise LLMError("stubbed failure", provider="openrouter", model=MODEL)

    with pytest.raises(Exception):
        write_bullets("experience", "cut page load from 2s to 400ms",
                      llm=ask_charging_budget)

    # One counter, so the sum across the outer loop's calls is the total.
    assert sum(charged) <= MAX_CALLS_PER_PRESS, charged
    assert fake_client.call_count <= MAX_CALLS_PER_PRESS, fake_client.call_count


def test_a_press_that_succeeds_first_time_spends_one_call() -> None:
    """The budget must not make the common case slower or more expensive."""
    from pydantic import BaseModel

    class Out(BaseModel):
        answer: str

    budget = CallBudget()
    client = FakeClient(replies=['{"answer": "ok"}'])
    got = ask(Out, "hello", settings=settings_for(), client=client, budget=budget)
    assert got.answer == "ok"
    assert budget.spent == 1, budget.spent
    assert client.call_count == 1


def test_a_good_reply_and_then_a_guard_retry_stays_under_the_cap() -> None:
    """The realistic worst case: the model answers, the guard rejects it, the
    retry answers too. Two calls, then it stops -- even though each layer alone
    would allow two more."""
    from app.assist import write_bullets

    calls = {"n": 0}

    def ask_repeating_a_bad_bullet(schema, prompt, *, settings=None, client=None,
                                   budget=None):
        assert budget is not None, "write_bullets did not pass a budget to ask"
        calls["n"] += 1
        budget.take()
        # No numbers in the bullets, while the source has plenty: the fact guard
        # trips, which is what sends write_bullets round its own loop again.
        return schema.model_validate(
            {"bullets": [{"text": "collaborated with the team"}],
             "numbered_facts": [], "unused_facts": [], "shared_facts": []}
        )

    write_bullets("experience", "cut page load from 2s to 400ms",
                  llm=ask_repeating_a_bad_bullet)
    assert calls["n"] <= MAX_CALLS_PER_PRESS, calls["n"]