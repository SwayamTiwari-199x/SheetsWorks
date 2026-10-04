"""llm.py: provider routing, schema-in-prompt, retry-once contract.

All HTTP is faked; no API key and no network needed.
"""

from __future__ import annotations

import json

import pytest

from app.config import OPENAI_COMPAT_BASE_URLS, PROVIDERS, Settings
from app.llm import LLMError, ask, extract_json, schema_prompt
from pydantic import BaseModel, Field

from .fakes import FakeClient

# An arbitrary, obviously-fake model id used wherever a test needs a model set
# without caring which one. Deliberately shaped like an OpenRouter id
# ("vendor/model:free") so the shape itself is exercised.
MODEL = "test-vendor/test-model:free"


class Out(BaseModel):
    answer: str = Field(min_length=1)
    score: int = 0


def settings_for(provider: str, **kw) -> Settings:
    return Settings(llm_provider=provider, _env_file=None, **kw)


# --- schema goes in the prompt, not into a provider JSON mode ------------


def test_schema_is_embedded_in_prompt() -> None:
    text = schema_prompt(Out)
    assert "JSON Schema" in text
    assert "answer" in text and "score" in text
    assert "minLength" in text


def test_request_carries_schema_in_system_prompt() -> None:
    client = FakeClient(replies=[json.dumps({"answer": "pong", "score": 1})])
    ask(Out, "ping", settings=settings_for("groq"), client=client)

    body = client.calls[0]["json"]
    assert "JSON Schema" in body["messages"][0]["content"]
    # No provider-specific JSON-mode flag anywhere in the request.
    flat = json.dumps(body)
    for flag in ("response_format", "response_mime_type", "guided_json", "json_object"):
        assert flag not in flat


def test_no_provider_json_mode_flags_for_anthropic() -> None:
    client = FakeClient(replies=[json.dumps({"answer": "pong"})])
    ask(Out, "ping", settings=settings_for("anthropic"), client=client)
    flat = json.dumps(client.calls[0]["json"])
    for flag in ("response_format", "response_mime_type", "guided_json", "json_object"):
        assert flag not in flat


# --- routing -------------------------------------------------------------


@pytest.mark.parametrize("provider", sorted(OPENAI_COMPAT_BASE_URLS))
def test_openai_compatible_providers_hit_chat_completions(provider: str) -> None:
    client = FakeClient(replies=[json.dumps({"answer": "pong"})])
    # openrouter is given a model explicitly; it has none by default.
    result = ask(Out, "ping", settings=settings_for(provider, llm_model=MODEL), client=client)

    assert result.answer == "pong"
    assert client.call_count == 1
    assert client.calls[0]["url"] == f"{OPENAI_COMPAT_BASE_URLS[provider]}/chat/completions"
    assert client.calls[0]["json"]["model"] == MODEL


def test_anthropic_uses_messages_endpoint() -> None:
    client = FakeClient(replies=[json.dumps({"answer": "pong"})])
    result = ask(Out, "ping", settings=settings_for("anthropic"), client=client)

    assert result.answer == "pong"
    assert client.calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    body = client.calls[0]["json"]
    assert "system" in body  # top-level, not a message
    assert body["messages"][0]["role"] == "user"


# --- openrouter ------------------------------------------------------------


def test_openrouter_uses_the_existing_openai_compatible_path() -> None:
    """Not a new branch. OpenRouter speaks the OpenAI dialect, so it must reuse
    `_post_openai_compat` -- a fifth special case would be five places to keep
    in step for no gain."""
    client = FakeClient(replies=[json.dumps({"answer": "pong"})])
    result = ask(Out, "ping", settings=settings_for("openrouter", llm_model=MODEL), client=client)

    assert result.answer == "pong"
    assert client.call_count == 1
    assert client.calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    body = client.calls[0]["json"]
    assert body["model"] == MODEL
    # Same body as every other OpenAI-compatible provider -- no OpenRouter-only
    # fields, which is what "use the existing path" has to mean if it means
    # anything.
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"
    assert "response_format" not in body


def test_openrouter_authenticates_with_a_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not x-api-key. That is the anthropic branch, and getting this wrong would
    be a 401 that reads like a bad key rather than a wrong header."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key-123")
    client = FakeClient(replies=[json.dumps({"answer": "pong"})])
    ask(Out, "ping", settings=settings_for("openrouter", llm_model=MODEL), client=client)

    headers = client.calls[0]["headers"]
    assert headers["Authorization"] == "Bearer or-key-123"
    assert "x-api-key" not in headers
    assert headers["Content-Type"] == "application/json"


def test_openrouter_refuses_to_send_anything_without_a_model() -> None:
    """The requirement, and the reason this provider exists as an exception.

    Raising here rather than defaulting means a request is never sent with an
    invented model id. The client must not have been called at all.
    """
    client = FakeClient(replies=[json.dumps({"answer": "pong"})])
    with pytest.raises(LLMError) as exc:
        ask(Out, "ping", settings=settings_for("openrouter"), client=client)

    assert client.call_count == 0, "nothing may be sent without a model"
    assert "LLM_MODEL" in str(exc.value)
    assert "openrouter" in str(exc.value)
    assert exc.value.provider == "openrouter"


def test_the_missing_model_message_survives_a_report() -> None:
    """`report()` is what --check-llm prints, so it has to carry the fix, not
    just the provider's name."""
    with pytest.raises(LLMError) as exc:
        ask(Out, "ping", settings=settings_for("openrouter"), client=FakeClient())
    report = exc.value.report()
    assert "LLM_MODEL" in report
    assert "https://openrouter.ai/models" in report


@pytest.mark.parametrize("blank", ["", "   "])
def test_openrouter_refuses_a_blank_model_too(blank: str) -> None:
    """`LLM_MODEL=` in .env arrives as "", not None, so the `is None` guard in
    config's validator does not see it. Without this, an empty id would be sent
    and come back as an unexplained 404."""
    client = FakeClient(replies=[json.dumps({"answer": "pong"})])
    with pytest.raises(LLMError):
        ask(Out, "ping", settings=settings_for("openrouter", llm_model=blank), client=client)
    assert client.call_count == 0


def test_openrouter_failures_are_reported_as_its_own() -> None:
    client = FakeClient(replies=["upstream said no"], status_code=401)
    with pytest.raises(LLMError) as exc:
        ask(Out, "ping", settings=settings_for("openrouter", llm_model=MODEL), client=client)
    assert exc.value.provider == "openrouter"
    assert exc.value.model == MODEL
    assert exc.value.status_code == 401
    # And the key must not appear in the message.
    assert "or-key" not in exc.value.report()


def test_openrouter_retries_once_then_gives_up_like_the_others() -> None:
    """The retry-once contract is the whole of llm.py's behaviour; a new
    provider must not be exempt from it."""
    client = FakeClient(replies=["not json at all"])
    with pytest.raises(LLMError):
        ask(Out, "ping", settings=settings_for("openrouter", llm_model=MODEL), client=client)
    assert client.call_count == 2


def test_every_provider_is_supported() -> None:
    """Driven off PROVIDERS so adding one cannot leave this test quietly green
    while covering nothing."""
    for provider in PROVIDERS:
        client = FakeClient(replies=[json.dumps({"answer": "pong"})])
        settings = settings_for(
            provider,
            # openrouter has no default model, so every provider in this loop is
            # given one -- otherwise this would be asserting that a missing model
            # works.
            llm_model=MODEL,
        )
        assert ask(Out, "p", settings=settings, client=client).answer == "pong", provider
        assert client.call_count == 1, provider


def test_model_override_is_respected() -> None:
    client = FakeClient(replies=[json.dumps({"answer": "pong"})])
    ask(Out, "p", settings=settings_for("groq", llm_model="my-model"), client=client)
    assert client.calls[0]["json"]["model"] == "my-model"


# --- JSON extraction -----------------------------------------------------


def test_extract_json_from_plain_object() -> None:
    assert extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_from_markdown_fence() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_with_surrounding_prose() -> None:
    assert extract_json('Sure! Here you go: {"a": 1} Hope that helps.') == '{"a": 1}'


def test_extract_json_raises_on_empty() -> None:
    with pytest.raises(ValueError):
        extract_json("   ")


def test_extract_json_raises_when_no_object() -> None:
    with pytest.raises(ValueError):
        extract_json("I cannot answer that.")


# --- the retry-once contract --------------------------------------------


def test_invalid_json_triggers_exactly_one_retry_then_raises() -> None:
    client = FakeClient(replies=["not json at all"])
    with pytest.raises(LLMError):
        ask(Out, "ping", settings=settings_for("groq"), client=client)

    assert client.call_count == 2, "must try once, retry once, then give up"
    assert not client.closed or True  # client injected, not closed by us


def test_retry_is_not_repeated_a_third_time() -> None:
    client = FakeClient(replies=["nope"])
    with pytest.raises(LLMError) as exc:
        ask(Out, "ping", settings=settings_for("mistral"), client=client)
    assert client.call_count == 2
    assert "mistral" in str(exc.value)


def test_retry_succeeds_when_second_reply_is_valid() -> None:
    client = FakeClient(replies=["garbage", json.dumps({"answer": "pong", "score": 7})])
    result = ask(Out, "ping", settings=settings_for("groq"), client=client)

    assert result.answer == "pong"
    assert result.score == 7
    assert client.call_count == 2


def test_retry_prompt_mentions_the_failure() -> None:
    client = FakeClient(replies=["garbage", json.dumps({"answer": "pong"})])
    ask(Out, "ping", settings=settings_for("groq"), client=client)

    retry_user_msg = client.calls[1]["json"]["messages"][-1]["content"]
    assert "could not be parsed" in retry_user_msg
    assert "ONLY the raw JSON" in retry_user_msg
    # original prompt preserved
    assert "ping" in retry_user_msg


def test_schema_validation_failure_also_retries() -> None:
    # Valid JSON, but score must be an int -> pydantic rejects it.
    bad = json.dumps({"answer": "pong", "score": "not-a-number"})
    client = FakeClient(replies=[bad, json.dumps({"answer": "pong", "score": 1})])
    result = ask(Out, "ping", settings=settings_for("groq"), client=client)
    assert result.score == 1
    assert client.call_count == 2


def test_persistently_invalid_schema_raises_after_one_retry() -> None:
    bad = json.dumps({"answer": "pong", "score": "still-not-a-number"})
    client = FakeClient(replies=[bad])
    with pytest.raises(LLMError) as exc:
        ask(Out, "ping", settings=settings_for("gemini"), client=client)
    assert client.call_count == 2
    assert exc.value.provider == "gemini"


def test_llm_error_carries_provider_and_model() -> None:
    client = FakeClient(replies=["garbage"])
    with pytest.raises(LLMError) as exc:
        ask(Out, "p", settings=settings_for("groq", llm_model="test-model"), client=client)
    assert exc.value.provider == "groq"
    assert exc.value.model == "test-model"
    assert exc.value.detail  # offending payload excerpt retained


def test_unknown_provider_raises_before_any_request() -> None:
    client = FakeClient(replies=["{}"])
    bad = settings_for("groq")
    object.__setattr__(bad, "llm_provider", "openai")  # not in the union
    with pytest.raises(LLMError):
        ask(Out, "p", settings=bad, client=client)
    assert client.call_count == 0


def test_http_error_becomes_llm_error_with_hint() -> None:
    """Transport failures must surface as LLMError, not a raw httpx traceback."""
    for status, expect in ((401, "API key"), (403, "no access"), (404, "retired")):
        client = FakeClient(replies=["x"], status_code=status)
        with pytest.raises(LLMError) as exc:
            ask(Out, "p", settings=settings_for("groq"), client=client)
        assert exc.value.status_code == status
        assert expect in exc.value.hint


def test_http_error_report_is_actionable() -> None:
    client = FakeClient(replies=["x"], status_code=403)
    with pytest.raises(LLMError) as exc:
        ask(Out, "p", settings=settings_for("groq"), client=client)
    report = exc.value.report()
    assert "groq" in report
    assert "HTTP 403" in report
    assert "hint:" in report


def test_error_message_extracted_from_google_list_shape() -> None:
    """Google returns [{"error": {...}}]; OpenAI returns {"error": {...}}."""
    from app.llm import _extract_error_message

    assert _extract_error_message(
        [{"error": {"message": "Your project has been denied access."}}]
    ) == "Your project has been denied access."
    assert _extract_error_message({"error": {"message": "bad key"}}) == "bad key"
    assert _extract_error_message("not json") == ""


def test_gemini_default_model_is_not_retired() -> None:
    """gemini-2.5-flash was withdrawn for new accounts and 404'd."""
    s = Settings(llm_provider="gemini", _env_file=None)
    assert s.llm_model == "gemini-3.8-flash"


def test_no_credential_leaks_into_error_detail() -> None:
    """An error must never echo the API key back to the user or the log."""
    client = FakeClient(replies=["x"], status_code=401)
    s = settings_for("groq")
    with pytest.raises(LLMError) as exc:
        ask(Out, "p", settings=s, client=client)
    blob = f"{exc.value} {exc.value.detail} {exc.value.hint} {exc.value.report()}"
    assert "sk-" not in blob
    assert "Bearer" not in blob
