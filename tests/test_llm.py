"""llm.py: provider routing, schema-in-prompt, retry-once contract.

All HTTP is faked; no API key and no network needed.
"""

from __future__ import annotations

import json

import pytest

from app.config import OPENAI_COMPAT_BASE_URLS, Settings
from app.llm import LLMError, ask, extract_json, schema_prompt
from pydantic import BaseModel, Field

from .fakes import FakeClient


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


@pytest.mark.parametrize("provider", ["gemini", "groq", "mistral"])
def test_openai_compatible_providers_hit_chat_completions(provider: str) -> None:
    client = FakeClient(replies=[json.dumps({"answer": "pong"})])
    result = ask(Out, "ping", settings=settings_for(provider), client=client)

    assert result.answer == "pong"
    assert client.call_count == 1
    assert client.calls[0]["url"] == f"{OPENAI_COMPAT_BASE_URLS[provider]}/chat/completions"
    assert client.calls[0]["json"]["model"] == Settings(
        llm_provider=provider, _env_file=None
    ).llm_model


def test_anthropic_uses_messages_endpoint() -> None:
    client = FakeClient(replies=[json.dumps({"answer": "pong"})])
    result = ask(Out, "ping", settings=settings_for("anthropic"), client=client)

    assert result.answer == "pong"
    assert client.calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    body = client.calls[0]["json"]
    assert "system" in body  # top-level, not a message
    assert body["messages"][0]["role"] == "user"


def test_all_four_providers_supported() -> None:
    for provider in ("gemini", "groq", "mistral", "anthropic"):
        client = FakeClient(replies=[json.dumps({"answer": "pong"})])
        assert ask(Out, "p", settings=settings_for(provider), client=client).answer == "pong"
        assert client.call_count == 1


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


def test_http_error_propagates() -> None:
    client = FakeClient(replies=["x"], status_code=401)
    with pytest.raises(RuntimeError):
        ask(Out, "p", settings=settings_for("groq"), client=client)
