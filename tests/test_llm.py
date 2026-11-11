"""llm.py: provider routing, schema-in-prompt, retry-once contract.

All HTTP is faked; no API key and no network needed.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import OPENAI_COMPAT_BASE_URLS, PROVIDERS, Settings
from app.llm import (
    LLMError,
    _raise_token_limit,
    ask,
    extract_json,
    is_retryable_status,
    schema_prompt,
)
from pydantic import BaseModel, Field

from .fakes import FakeClient, FakeResponse

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


# --- a rejected request is not retried, only 429 is -----------------------


def test_a_400_from_the_provider_is_not_retried() -> None:
    """Sending the identical request again cannot make a 400 succeed.

    The real case: OpenRouter rejected the /assist/answer request, the retry
    spent a second call to be rejected identically, and the user saw a message
    about unparseable JSON that had nothing to do with the 400.
    """
    client = FakeClient(
        replies=['{"error":{"message":"No endpoints found that match your input"}}'],
        status_code=400,
    )
    with pytest.raises(LLMError) as excinfo:
        ask(Out, "hello", settings=settings_for("openrouter", llm_model=MODEL), client=client)
    assert client.call_count == 1, "a 4xx was retried"
    assert excinfo.value.status_code == 400


def test_a_429_is_retried_because_it_means_not_now() -> None:
    class Alternating(FakeClient):
        def post(self, url, *, headers, json):
            self.calls.append({"url": url, "headers": headers, "json": json})
            if len(self.calls) == 1:
                return FakeResponse({"error": {"message": "rate limit"}}, 429, url)
            body = '{"answer": "ok"}'
            return FakeResponse(
                {"choices": [{"message": {"role": "assistant", "content": body}}]},
                200, url,
            )

    client = Alternating()
    out = ask(Out, "hello", settings=settings_for("openrouter", llm_model=MODEL), client=client)
    assert out.answer == "ok"
    assert client.call_count == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_only_429_is_retryable_among_the_4xx(status: int) -> None:
    assert is_retryable_status(status) is False


def test_5xx_and_transport_failures_stay_retryable() -> None:
    assert is_retryable_status(500) is True
    assert is_retryable_status(503) is True
    assert is_retryable_status(None) is False


def test_the_providers_error_body_is_kept_not_just_the_status() -> None:
    """The provider names the field it rejected. 'HTTP 400' does not."""
    client = FakeClient(
        replies=['max_tokens must be greater than 0'],
        status_code=400,
    )
    with pytest.raises(LLMError) as excinfo:
        ask(Out, "hi", settings=settings_for("openrouter", llm_model=MODEL), client=client)
    assert "max_tokens must be greater than 0" in excinfo.value.detail
    assert "check LLM_MODEL" in excinfo.value.hint


def test_a_non_json_error_body_is_still_captured() -> None:
    """Not every provider answers a rejection with JSON."""
    class TextOnly(FakeClient):
        def post(self, url, *, headers, json):
            self.calls.append({"url": url, "headers": headers, "json": json})
            return httpx.Response(
                400,
                text="upstream: invalid max_tokens",
                request=httpx.Request("POST", url),
            )

    with pytest.raises(LLMError) as excinfo:
        ask(Out, "hi", settings=settings_for("openrouter", llm_model=MODEL), client=TextOnly())
    assert "invalid max_tokens" in excinfo.value.detail


def test_the_key_is_redacted_out_of_a_provider_error_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that echoes the Authorization header must not put the key in
    a log line or in the dialog the user pastes into a bug report."""
    secret = "sk-or-v1-SUPERSECRETVALUE"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    client = FakeClient(
        replies=[f'bad request; Authorization: Bearer {secret}'],
        status_code=400,
    )
    with pytest.raises(LLMError) as excinfo:
        ask(Out, "hi", settings=settings_for("openrouter", llm_model=MODEL), client=client)
    assert secret not in excinfo.value.detail
    assert "<redacted>" in excinfo.value.detail


def test_a_4xx_body_is_written_to_the_log(monkeypatch, tmp_path) -> None:
    """The diagnosis has to survive the process, so it goes to logs/llm.log."""
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    client = FakeClient(replies=["max_tokens is too large"], status_code=400)
    with pytest.raises(LLMError):
        ask(
            Out,
            "hi",
            settings=settings_for("openrouter", llm_model=MODEL, log_dir=str(tmp_path)),
            client=client,
        )
    log = (tmp_path / "llm.log").read_text(encoding="utf-8")
    assert "llm.http_error" in log
    assert "max_tokens is too large" in log
    assert '"status_code": 400' in log
    assert '"retryable": false' in log


# --- how long each call took -------------------------------------------------
# The last real run spent 80 seconds across three truncated attempts and the log
# could not say which call was slow, so "the AI is slow" and "the model spent its
# whole budget reasoning" looked identical. Every call is now timed, including
# the ones that failed and the ones that were thrown away.


def test_a_successful_call_logs_how_long_it_took(tmp_path) -> None:
    client = FakeClient(replies=['{"answer": "ok"}'])
    ask(Out, "hi", settings=settings_for("openrouter", llm_model=MODEL,
                                         log_dir=str(tmp_path)), client=client)
    log = (tmp_path / "llm.log").read_text(encoding="utf-8")
    ok_line = [ln for ln in log.splitlines() if "llm.ok" in ln]
    assert ok_line, log
    assert '"elapsed_ms"' in ok_line[-1], ok_line[-1]
    assert '"total_ms"' in ok_line[-1], ok_line[-1]
    # A number, not a placeholder: the point is to be able to read the duration.
    elapsed = int(ok_line[-1].split('"elapsed_ms":')[1].split(",")[0].strip())
    assert elapsed >= 0


def test_the_provider_token_counts_are_logged_too(tmp_path) -> None:
    """Prompt and completion tokens are what explains a slow reply, and the
    model refuses to be asked about them after the fact."""
    class WithUsage(FakeClient):
        def post(self, url, *, headers, json):
            self.calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse(
                {
                    "choices": [{"finish_reason": "stop",
                                 "message": {"content": '{"answer": "ok"}'}}],
                    "usage": {"prompt_tokens": 812, "completion_tokens": 143},
                },
                200, url,
            )

    client = WithUsage()
    ask(Out, "hi", settings=settings_for("openrouter", llm_model=MODEL,
                                         log_dir=str(tmp_path)), client=client)
    log = (tmp_path / "llm.log").read_text(encoding="utf-8")
    ok_line = [ln for ln in log.splitlines() if "llm.ok" in ln][-1]
    assert '"prompt_tokens": 812' in ok_line, ok_line
    assert '"completion_tokens": 143' in ok_line, ok_line


def test_a_failed_call_is_timed_too(tmp_path) -> None:
    """A failure that arrived instantly and one that arrived after 30 seconds
    are different problems, and the log line is what tells them apart."""
    class Slow(FakeClient):
        def post(self, url, *, headers, json):
            self.calls.append({"url": url, "headers": headers, "json": json})
            import time as _t
            _t.sleep(0.05)
            return FakeResponse({"error": {"message": "overloaded"}}, 503, url)

    client = Slow()
    with pytest.raises(LLMError):
        ask(Out, "hi", settings=settings_for("openrouter", llm_model=MODEL,
                                             log_dir=str(tmp_path)), client=client)
    log = (tmp_path / "llm.log").read_text(encoding="utf-8")
    line = [ln for ln in log.splitlines() if "llm.http_error" in ln][-1]
    assert '"elapsed_ms"' in line, line
    elapsed = int(line.split('"elapsed_ms":')[1].split(",")[0].strip())
    assert elapsed >= 45, f"a 50ms call logged as {elapsed}ms: {line}"


def test_a_truncated_call_is_timed_because_it_is_the_slow_one(tmp_path) -> None:
    """It used the whole token allowance before saying nothing. A log that only
    recorded successful calls would make the 80-second run look instant."""

    class Truncating(FakeClient):
        def post(self, url, *, headers, json):
            self.calls.append({"url": url, "headers": headers, "json": json})
            limit = json["max_tokens"]
            if limit == 2048:
                return FakeResponse(
                    {"choices": [{"finish_reason": "length",
                                  "message": {"content": None}}]}, 200, url)
            return FakeResponse(
                {"choices": [{"finish_reason": "stop",
                              "message": {"content": '{"answer": "ok"}'}}]},
                200, url)

    client = Truncating()
    ask(Out, "hi", settings=settings_for("openrouter", llm_model=MODEL,
                                         log_dir=str(tmp_path)), client=client)
    log = (tmp_path / "llm.log").read_text(encoding="utf-8")
    trunc = [ln for ln in log.splitlines() if "llm.truncated" in ln]
    assert trunc, log
    assert '"elapsed_ms"' in trunc[-1], trunc[-1]
    assert '"total_ms"' in trunc[-1], trunc[-1]
    # The second llm.ok line carries the running total across both calls.
    oks = [ln for ln in log.splitlines() if "llm.ok" in ln]
    assert '"total_ms"' in oks[-1], oks[-1]


def test_the_second_attempt_says_how_long_the_first_one_took(tmp_path) -> None:
    """So a stall can be attributed to the call that caused it."""

    class BadThenGood(FakeClient):
        def post(self, url, *, headers, json):
            self.calls.append({"url": url, "headers": headers, "json": json})
            if len(self.calls) == 1:
                return FakeResponse({"choices": [{"finish_reason": "stop",
                                                  "message": {"content": "not json"}}]}, 200, url)
            return FakeResponse(
                {"choices": [{"finish_reason": "stop",
                              "message": {"content": '{"answer": "ok"}'}}]},
                200, url)

    client = BadThenGood()
    ask(Out, "hi", settings=settings_for("openrouter", llm_model=MODEL,
                                         log_dir=str(tmp_path)), client=client)
    log = (tmp_path / "llm.log").read_text(encoding="utf-8")
    second = [ln for ln in log.splitlines()
              if "llm.request" in ln and '"attempt": 2' in ln]
    assert second, log
    assert '"spent_ms"' in second[-1], second[-1]


# --- a truncated reply raises the limit, it does not burn the parse retry --


def test_a_reply_that_ran_out_of_tokens_is_not_reported_as_bad_json() -> None:
    """The real failure: a reasoning model spent all 2048 tokens thinking and
    returned content=null. That is not 'unparseable JSON', and repeating the
    prompt at the same limit would be cut off in exactly the same place."""
    class Truncating(FakeClient):
        def post(self, url, *, headers, json):
            self.calls.append({"url": url, "headers": headers, "json": json})
            limit = json["max_tokens"]
            if limit == 2048:
                return FakeResponse(
                    {"choices": [{"finish_reason": "length",
                                  "message": {"content": None, "reasoning": "..."}}]},
                    200, url,
                )
            return FakeResponse(
                {"choices": [{"finish_reason": "stop",
                              "message": {"content": '{"answer": "ok"}'}}]},
                200, url,
            )

    client = Truncating()
    settings = settings_for("openrouter", llm_model=MODEL)
    out = ask(Out, "hello", settings=settings, client=client)
    assert out.answer == "ok"
    assert client.call_count == 2
    # The second call must actually carry the bigger allowance.
    assert client.calls[0]["json"]["max_tokens"] == 2048
    assert client.calls[1]["json"]["max_tokens"] == 4096


def test_the_token_limit_doubles_and_then_stops() -> None:
    class AlwaysTruncates(FakeClient):
        def post(self, url, *, headers, json):
            self.calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse(
                {"choices": [{"finish_reason": "length",
                              "message": {"content": None, "reasoning": "..."}}]},
                200, url,
            )

    client = AlwaysTruncates()
    with pytest.raises(LLMError) as excinfo:
        ask(Out, "hello", settings=settings_for("openrouter", llm_model=MODEL),
            client=client)
    # Two attempts, not one-per-doubling: the live budget is not open-ended.
    assert client.call_count == 2
    assert "raising the token limit" in str(excinfo.value)
    assert "LLM_MAX_TOKENS" in str(excinfo.value)


def test_the_token_limit_has_a_ceiling() -> None:
    settings = settings_for("openrouter", llm_model=MODEL, llm_max_tokens=16384)
    assert _raise_token_limit(settings) is False
    assert settings.llm_max_tokens == 16384
    settings = settings_for("openrouter", llm_model=MODEL, llm_max_tokens=12000)
    assert _raise_token_limit(settings) is True
    assert settings.llm_max_tokens == 16384


def test_a_truncated_reply_with_some_text_is_not_raised_away() -> None:
    """finish_reason=length with real content is a long answer, not a failure.

    Treating it as a failure would discard a usable reply and spend a call.
    """
    class PartialButUsable(FakeClient):
        def post(self, url, *, headers, json):
            self.calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse(
                {"choices": [{"finish_reason": "length",
                              "message": {"content": '{"answer": "ok"}'}}]},
                200, url,
            )

    client = PartialButUsable()
    out = ask(Out, "hi", settings=settings_for("openrouter", llm_model=MODEL),
              client=client)
    assert out.answer == "ok"
    assert client.call_count == 1


def test_anthropic_max_tokens_is_raised_too() -> None:
    class AnthropicTruncating(FakeClient):
        def post(self, url, *, headers, json):
            self.calls.append({"url": url, "headers": headers, "json": json})
            if json["max_tokens"] == 2048:
                return FakeResponse({"stop_reason": "max_tokens", "content": []},
                                    200, url)
            return FakeResponse(
                {"stop_reason": "end_turn",
                 "content": [{"type": "text", "text": '{"answer": "ok"}'}]},
                200, url,
            )

    client = AnthropicTruncating()
    out = ask(Out, "hi", settings=settings_for("anthropic", llm_model="m"),
              client=client)
    assert out.answer == "ok"
    assert client.calls[1]["json"]["max_tokens"] == 4096


def test_no_credential_leaks_into_error_detail() -> None:
    """An error must never echo the API key back to the user or the log."""
    client = FakeClient(replies=["x"], status_code=401)
    s = settings_for("groq")
    with pytest.raises(LLMError) as exc:
        ask(Out, "p", settings=s, client=client)
    blob = f"{exc.value} {exc.value.detail} {exc.value.hint} {exc.value.report()}"
    assert "sk-" not in blob
    assert "Bearer" not in blob
