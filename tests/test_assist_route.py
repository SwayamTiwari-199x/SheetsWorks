"""The failing 'Tell the AI' flow, pinned.

The bug: POST /assist/answer was bound to the `/assist/{section}` handler, so a
request carrying {"section", "facts", "answers"} was read as a request carrying
{"free_text"} and answered with 400 "free_text is required". The second step of
the AI flow could never run. Nothing was ever sent to the provider, so no amount
of reading the provider's error body would have found anything.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_assist_answer_is_not_swallowed_by_the_section_route(client: TestClient) -> None:
    """The literal route must be declared first, or {section} eats "answer"."""
    paths = [
        r.path for r in app.routes if getattr(r, "path", "").startswith("/assist")
    ]
    assert paths.index("/assist/answer") < paths.index("/assist/{section}"), (
        "POST /assist/answer will be matched by POST /assist/{section} "
        "and every call will 400 with 'free_text is required'"
    )


def test_assist_answer_reaches_the_writer_not_the_extractor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A well-formed body must get past the guards, not bounce off them."""
    from app import assist

    seen: dict = {}

    def fake_write(section, raw_facts, answers="", **kw):
        seen["section"] = section
        seen["facts"] = raw_facts
        seen["answers"] = answers
        return assist.BulletsResult(
            bullets=[assist.SuggestedBullet(text="Built it", facts=[1])],
            numbered_facts=["worked on the backend"],
            unused_facts=[],
            reused_metrics=[],
        )

    monkeypatch.setattr(assist, "write_bullets", fake_write)
    r = client.post("/assist/answer", json={
        "section": "experience",
        "facts": "worked on the backend",
        "answers": "1. my part",
    })
    assert r.status_code == 200, r.text
    assert r.json()["bullets"][0]["text"] == "Built it"
    assert seen == {
        "section": "experience", "facts": "worked on the backend", "answers": "1. my part",
    }


def test_the_400_that_the_user_saw_is_gone(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exactly the request that failed: section + facts + answers.

    `write_bullets` is stubbed. Left unstubbed this test posted a well-formed
    body to the real provider on every suite run -- conftest scrubs the API key,
    so it cost one real HTTP request per run in exchange for a 401 and taught us
    nothing. A route test asserts about routing.
    """
    from app import assist

    monkeypatch.setattr(
        assist, "write_bullets",
        lambda section, raw_facts, answers="", **kw: assist.BulletsResult(
            bullets=[], numbered_facts=[], unused_facts=[], reused_metrics=[],
        ),
    )
    r = client.post("/assist/answer", json={
        "section": "experience",
        "facts": "worked on backend for a staffing app using FastAPI and Postgres",
        "answers": "1. 120 recruiters\n2. cut page load from 2s to 400ms",
    })
    assert r.status_code != 400 or "free_text" not in r.text, r.text


def test_a_missing_section_is_still_a_400(client: TestClient) -> None:
    r = client.post("/assist/answer", json={"facts": "x"})
    assert r.status_code == 400
    assert r.json()["detail"] == "section is required"


def test_missing_facts_is_still_a_400(client: TestClient) -> None:
    r = client.post("/assist/answer", json={"section": "experience", "facts": "  "})
    assert r.status_code == 400
    assert r.json()["detail"] == "facts is required"


def test_an_unsupported_section_is_a_400_not_a_502(client: TestClient) -> None:
    r = client.post("/assist/answer", json={"section": "summary", "facts": "x"})
    assert r.status_code == 400
    assert "does not support" in r.json()["detail"]


def test_a_provider_400_surfaces_as_a_502_carrying_its_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller's request was fine. Something outside this app failed, and
    the one sentence that helps is the provider's own."""
    from app import assist
    from app.llm import LLMError

    def boom(section, raw_facts, answers="", **kw):
        raise LLMError(
            "HTTP 400 from openrouter",
            provider="openrouter",
            model="test/model:free",
            detail="max_tokens must be less than the model maximum",
            status_code=400,
        )

    monkeypatch.setattr(assist, "write_bullets", boom)
    r = client.post("/assist/answer", json={"section": "experience", "facts": "x"})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "openrouter" in detail
    assert "HTTP 400" in detail
    assert "max_tokens must be less than the model maximum" in detail


def test_a_provider_failure_on_the_extract_route_is_also_a_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import assist
    from app.llm import LLMError

    def boom(section, free_text, **kw):
        raise LLMError(
            "HTTP 401 from openrouter",
            provider="openrouter", model="m",
            detail="No auth credentials found", status_code=401,
        )

    monkeypatch.setattr(assist, "ask_clarifying", boom)
    r = client.post("/assist/experience", json={"free_text": "did backend work"})
    assert r.status_code == 502
    assert "No auth credentials found" in r.json()["detail"]


def test_a_provider_failure_with_no_detail_still_says_something_useful(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import assist
    from app.llm import LLMError

    def boom(section, raw_facts, answers="", **kw):
        raise LLMError("boom", provider="groq", model="m", status_code=500)

    monkeypatch.setattr(assist, "write_bullets", boom)
    r = client.post("/assist/answer", json={"section": "experience", "facts": "x"})
    assert r.status_code == 502
    assert "groq" in r.json()["detail"]
    assert "No further detail" in r.json()["detail"]


# --- the call budget is our own limit, not the provider's ------------------


def test_a_spent_budget_reaches_the_caller_with_its_sentence_intact(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A budget message that survives the route.

    The provider-failure path reads `detail`, `status_code` and `provider`. A
    budget error has none of them -- the provider was perfectly happy, it simply
    answered three times -- so it fell through to "budget rejected the request.
    No further detail was returned." The two facts the reader needs, that three
    calls were spent and that nothing was saved, were both dropped on the floor
    of the error handler.
    """
    from app import assist
    from app.llm import CallBudget

    def spent(section, raw_facts, answers="", **kw):
        budget = CallBudget(limit=1)
        budget.take()
        budget.take()  # refused: raises the thing under test

    monkeypatch.setattr(assist, "write_bullets", spent)
    r = client.post("/assist/answer", json={"section": "experience", "facts": "x"})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "nothing was saved" in detail.lower(), detail
    assert "1 provider call" in detail, detail
    # Not dressed up as a provider refusal: nothing refused it.
    assert "rejected the request" not in detail, detail
    assert "No further detail" not in detail, detail


def test_a_budget_error_is_its_own_type_not_guessed_at_from_a_string(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same sentence has to arrive on the extract route, which is a different
    route with its own handler. One type, both routes."""
    from app import assist
    from app.assist import ask_clarifying
    from app.llm import CallBudget

    def spent(section, raw_facts, answers="", **kw):
        budget = CallBudget(limit=1)
        budget.take()
        budget.take()

    monkeypatch.setattr(assist, "write_bullets", spent)
    r = client.post("/assist/answer", json={"section": "experience", "facts": "x"})
    assert "nothing was saved" in r.json()["detail"].lower()

    def spent_clarify(section, free_text, **kw):
        budget = CallBudget(limit=1)
        budget.take()
        budget.take()

    monkeypatch.setattr(assist, "ask_clarifying", spent_clarify)
    r = client.post("/assist/experience", json={"free_text": "did backend work"})
    assert "nothing was saved" in r.json()["detail"].lower()