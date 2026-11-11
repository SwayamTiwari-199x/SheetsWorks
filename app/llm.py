"""LLM wrapper.

Public surface is deliberately tiny::

    from pydantic import BaseModel
    class Out(BaseModel):
        answer: str
    out = ask(Out, "What is 2+2?")

How it works
------------
The JSON schema is serialized **into the prompt**. No provider-specific JSON
modes / structured-output flags are used, so gemini, groq, mistral and
anthropic all behave identically and only the request/response envelope
differs:

- gemini, groq, mistral, openrouter -> one OpenAI-compatible
  ``/chat/completions`` path.
- anthropic -> a separate branch (``/messages``).

The reply is then extracted, ``json.loads``-ed, and validated with pydantic.
A failure at any of those steps triggers **exactly one retry**; a second
failure raises :class:`LLMError`.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import PROVIDERS, Settings, get_settings

logger = logging.getLogger("app.llm")

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 2  # first try + one retry, *within one budget*

# One button press, one budget, counted in provider calls.
#
# `MAX_ATTEMPTS` above bounds a single `ask()`. `write_bullets` runs the whole
# call again on top, so the two layers had independent counters and the worst
# case was their product: 2 x 2 = 4 live calls for one press, which is the whole
# of the product cap, leaving no room for a third failure. Raising either budget
# silently doubled the other.
#
# Three, not four, because the truncated-reply raise is itself a live call and
# has to be paid for out of the same three.
MAX_CALLS_PER_PRESS = 3


class CallBudgetExhausted(RuntimeError):
    """Our own limit stopped the work, not the provider.

    A type of its own because the two are rendered differently and handled
    differently. A provider failure is worth dressing up -- which provider,
    which status, what it said -- because the reader may be able to fix it. A
    spent budget has no provider, no status and no provider message to quote, so
    the generic rendering produced "budget rejected the request. No further
    detail was returned.", which is both untrue (nothing refused it) and
    useless (the sentence saying what happened was thrown away).

    Declared before LLMError because it is not an LLMError: a spent budget is
    not a failure of the provider or the model, and every existing
    `except LLMError` here would otherwise report it as one -- with a status
    code and a provider name, both of which would be invented. What it shares
    with a provider failure is the single job of stopping the work, so the
    handlers that only care about that check for both.
    """

    def __init__(self, message: str, *, limit: int):
        super().__init__(message)
        self.limit = limit

    def report(self) -> str:
        # No "[provider/model]" prefix: there is no provider here, and printing
        # one invents a culprit.
        return str(self)


class CallBudget:
    """A count of provider calls that outlives the function that spends it.

    `take()` is called immediately before every HTTP request, so a truncation
    retry costs the same as the first try. When it runs out it raises, and the
    message says both what happened and that nothing was saved -- a failure that
    looks like a success because the dialog merely stops updating is the worst
    outcome available here.
    """

    def __init__(self, limit: int = MAX_CALLS_PER_PRESS) -> None:
        self.limit = limit
        self.spent = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    def take(self) -> int:
        """Charge one provider call against the budget and return its number."""
        if self.spent >= self.limit:
            raise CallBudgetExhausted(
                f"Stopped after {self.limit} provider call"
                f"{'' if self.limit == 1 else 's'} for one action: the model kept "
                "answering with something unusable, and this app will not spend "
                "money without end. Nothing was saved. Try again, raise "
                "LLM_MAX_TOKENS in .env, or use a model that answers without a "
                "long reasoning prefix.",
                limit=self.limit,
            )
        self.spent += 1
        return self.spent


SYSTEM_PROMPT = (
    "You are a precise data-extraction service. Reply with a single JSON "
    "object and nothing else: no prose, no markdown fences, no commentary. "
    "Every key required by the schema must be present. Use only information "
    "present in the user's message; never invent facts, numbers, employers, "
    "dates or tool names."
)

SCHEMA_INSTRUCTION = (
    "Respond with JSON matching this JSON Schema exactly:\n{schema}\n"
    "The JSON object must be the entire reply."
)

RETRY_HINT = (
    "Your previous reply could not be parsed or did not match the schema. "
    "Reply again with ONLY the raw JSON object."
)


class LLMError(RuntimeError):
    """Raised after the single retry also fails, or on a provider-side failure."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        model: str,
        detail: str = "",
        status_code: int | None = None,
        hint: str = "",
    ):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.detail = detail
        self.status_code = status_code
        self.hint = hint

    def report(self) -> str:
        """Multi-line, actionable rendering for the CLI."""
        head = f"[{self.provider}/{self.model}] {self}"
        if self.detail:
            head += f"\n  provider said: {self.detail}"
        if self.hint:
            head += f"\n  hint: {self.hint}"
        return head


class TruncatedReply(ValueError):
    """The model used its whole allowance and returned nothing usable.

    A separate type from LLMError because it is not a failure of the provider --
    the request was accepted and answered -- it is an allowance that was too
    small. ``llm.py`` raises the limit and tries again; it must not spend the
    parse retry, because the second reply would be cut off at exactly the same
    place and be reported as unparseable JSON.
    """


def _extract_error_message(body: Any) -> str:
    """Pull the human-readable message out of a provider error body.

    Google returns a *list* of error objects where OpenAI returns a single
    object, so both shapes have to be handled.
    """
    try:
        payload = body
        if isinstance(payload, list) and payload:
            payload = payload[0]
        if isinstance(payload, dict):
            err = payload.get("error", payload)
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
    except Exception:
        pass
    return ""


# Status-specific advice. Every one of these has actually been hit during
# development, so they are written as fixes rather than restatements.
_STATUS_HINTS = {
    400: "The provider rejected the request shape; check LLM_MODEL and the max_tokens/temperature values.",
    401: "API key missing or invalid. Check the key for LLM_PROVIDER in .env.",
    403: (
        "Authenticated, but this account/project has no access to the model. "
        "On Google AI Studio / Cloud console enable the model for your project, "
        "or switch LLM_PROVIDER to a provider your key can reach."
    ),
    404: (
        "Unknown model or endpoint. The model id may be retired or the "
        "OpenAI-compatible route may not exist for it. Check LLM_MODEL."
    ),
    429: "Rate limit or quota exceeded. Wait, or check the provider's quota/billing.",
}


def _redact(text: str, secret: str | None) -> str:
    """Strip the API key out of a string that is about to be logged or shown.

    A provider error body is arbitrary text that a provider chooses. If any
    provider has ever echoed a request header back -- and some do, in verbose
    debug modes -- the key would otherwise end up in logs/llm.log and in the
    error dialog the user pastes into a bug report. Cheap to make impossible.
    """
    if not secret:
        return text
    return text.replace(secret, "<redacted>")


def _http_error(
    exc: Exception, settings: Settings, status_code: int
) -> LLMError:
    """Translate an httpx failure into an actionable LLMError.

    The provider's own message is kept in ``detail`` -- that is the sentence
    that says which field was rejected, and it is the whole reason to log the
    body rather than the status code.
    """
    message = ""
    detail = ""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.json()
            detail = _extract_error_message(body)
            if not detail:
                detail = json.dumps(body, default=str)[:600]
        except Exception:
            try:
                detail = response.text[:600]
            except Exception:
                detail = ""
        message = f"HTTP {status_code} from {settings.llm_provider}"
    else:
        message = f"{type(exc).__name__}: {exc}"
        detail = str(exc)[:600]

    return LLMError(
        message,
        provider=settings.llm_provider,
        model=str(settings.llm_model),
        detail=_redact(detail, settings.api_key),
        status_code=status_code,
        hint=_STATUS_HINTS.get(status_code, ""),
    )


# A 4xx means the request itself is wrong. Sending the identical request again
# cannot make it right, and on a metered endpoint it costs a call to prove that.
# 429 is the exception: it is the one 4xx that means "not now".
RETRYABLE_STATUSES: frozenset[int] = frozenset({429})


def is_retryable_status(status_code: int | None) -> bool:
    """Whether a failed request may be sent again unchanged.

    Only 429. Everything else in 4xx is a malformed or unacceptable request, so
    a second identical attempt is a guaranteed duplicate charge and a second
    identical failure. 5xx and transport errors are not 4xx and stay retryable
    by the caller's own judgement.
    """
    if status_code is None:
        return False
    if 400 <= status_code < 500:
        return status_code in RETRYABLE_STATUSES
    return True


def schema_prompt(schema: type[BaseModel]) -> str:
    """Render a pydantic model's JSON schema as prompt text."""
    return SCHEMA_INSTRUCTION.format(schema=json.dumps(schema.model_json_schema(), indent=2))


def _setup_logging(settings: Settings) -> None:
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(settings.log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    # One handler, re-pointed when the configured path changes. Adding a second
    # handler instead would leave earlier lines going to the old file, so a test
    # (or a second config in one process) would read a log file that had none of
    # the lines it just caused.
    handler._resume_builder = True  # type: ignore[attr-defined]
    for old in [h for h in logger.handlers if getattr(h, "_resume_builder", False)]:
        if getattr(old, "baseFilename", None) == settings.log_path:
            old.close()
            continue
        logger.removeHandler(old)
        old.close()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _log(settings: Settings, event: str, **fields: Any) -> None:
    _setup_logging(settings)
    logger.info(event, extra={"llm": fields})
    logger.info("%s %s", event, json.dumps(fields, default=str))


# --------------------------------------------------------------------------
# Response extraction
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> str:
    """Pull the JSON object out of a reply.

    Models occasionally wrap JSON in a markdown fence or add a sentence
    around it; both are recoverable, anything else is not.
    """
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


# --------------------------------------------------------------------------
# Transport: two branches, one surface
# --------------------------------------------------------------------------


# A reasoning model spends its budget on reasoning before it writes anything.
# On this provider the whole 2048-token allowance went into the thinking block
# and the reply came back with content=null and finish_reason="length". Retrying
# that prompt unchanged repeats it exactly, so a truncated reply raises the token
# limit instead: the request was fine, the allowance was not.
TRUNCATION_RAISE_FACTOR = 2
MAX_MAX_TOKENS = 16384


def _raise_token_limit(settings: Settings) -> bool:
    """Raise ``llm_max_tokens`` for another attempt. Returns whether it did."""
    raised = min(settings.llm_max_tokens * TRUNCATION_RAISE_FACTOR, MAX_MAX_TOKENS)
    if raised <= settings.llm_max_tokens:
        return False
    object.__setattr__(settings, "llm_max_tokens", raised)
    return True


def _choice(settings: Settings, payload: dict) -> str:
    """Return the reply text, or raise if the model ran out of budget.

    ``finish_reason == "length"`` with empty content is the failure worth
    handling specially: the model thought for the entire allowance and said
    nothing, which reads downstream as "unparseable JSON" and burns the retry on
    a prompt that will be cut off identically.
    """
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("provider returned no choices")
    first = choices[0]
    message = first.get("message") or {}
    content = message.get("content")
    if first.get("finish_reason") == "length" and not (content or "").strip():
        if _raise_token_limit(settings):
            raise TruncatedReply(
                f"the model used all {settings.llm_max_tokens // TRUNCATION_RAISE_FACTOR} "
                f"tokens reasoning and returned nothing; retrying with "
                f"{settings.llm_max_tokens}"
            )
    return content or ""


def _post_openai_compat(
    settings: Settings, client: httpx.Client, system: str, user: str
) -> tuple[str, dict]:
    """gemini / groq / mistral / openrouter: OpenAI chat-completions dialect."""
    resp = _post(
        client,
        f"{settings.base_url}/chat/completions",
        settings,
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        },
        body={
            "model": settings.llm_model,
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
    )
    payload = resp.json()
    return _choice(settings, payload), dict(payload.get("usage") or {})


def _post_anthropic(
    settings: Settings, client: httpx.Client, system: str, user: str
) -> tuple[str, dict]:
    """anthropic: system prompt is a top-level field, not a message."""
    resp = _post(
        client,
        f"{settings.base_url}/messages",
        settings,
        headers={
            "x-api-key": settings.api_key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        body={
            "model": settings.llm_model,
            "max_tokens": settings.llm_max_tokens,
            "temperature": settings.llm_temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
    )
    payload = resp.json()
    if payload.get("stop_reason") == "max_tokens" and not payload.get("content"):
        if _raise_token_limit(settings):
            raise TruncatedReply("reply hit max_tokens with no text; retrying larger")
    blocks = payload.get("content", [])
    return (
        "".join(b.get("text", "") for b in blocks if b.get("type") == "text"),
        dict(payload.get("usage") or {}),
    )


def _post(
    client: httpx.Client, url: str, settings: Settings, *, headers: dict, body: dict
):
    """POST and convert transport/HTTP failures into LLMError.

    Credentials are never put in an error message: only the status code and
    whatever text the provider chose to send back are surfaced, and the key is
    redacted from that text before it can reach a log or a dialog.

    A 4xx body is logged here, at the point where the status code is still
    known. Logging it further up would mean logging it without the status code,
    and "the provider said something" is not a diagnosis.

    The elapsed time is measured here, around the POST itself, so `llm.http_error`
    carries it too. A failure that arrived after 30 seconds is a different
    problem from one that arrived instantly, and the log line saying so is the
    difference between "retry it" and "the provider is down".
    """
    started = time.monotonic()
    try:
        resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        return resp
    except httpx.HTTPStatusError as exc:
        err = _http_error(exc, settings, exc.response.status_code)
        _log(
            settings,
            "llm.http_error",
            provider=settings.llm_provider,
            model=settings.llm_model,
            status_code=err.status_code,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            message=err.detail[:600],
            retryable=is_retryable_status(err.status_code),
        )
        raise err from None
    except httpx.HTTPError as exc:
        raise _http_error(exc, settings, 0) from None


def _complete(
    settings: Settings, client: httpx.Client, system: str, user: str
) -> tuple[str, dict]:
    """One request, one reply. Returns the raw text and the provider's token
    usage; raises TruncatedReply or LLMError. Timing is the caller's job, so a
    failure is measured on the same clock as a success."""
    if settings.llm_provider == "anthropic":
        return _post_anthropic(settings, client, system, user)
    return _post_openai_compat(settings, client, system, user)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def ask(
    schema: type[T],
    prompt: str,
    *,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
    budget: "CallBudget | None" = None,
) -> T:
    """Send ``prompt`` to the configured provider, return ``schema``-validated output.

    Retries once on invalid JSON or validation failure, then raises LLMError.

    ``budget`` is the caller's allowance for one user action. Pass the *same* one
    to every ``ask`` in that action: a fresh budget per call would restore the
    problem this exists to fix, because each layer would again be unable to see
    what the other had spent. Without one, this call gets a budget of its own,
    which is the old behaviour and is fine for a one-shot.
    """
    settings = settings or get_settings()
    if settings.llm_provider not in PROVIDERS:
        raise LLMError(
            f"unknown provider {settings.llm_provider!r}",
            provider=str(settings.llm_provider),
            model=str(settings.llm_model),
        )

    # Checked here rather than in config's validator, so Settings still builds
    # and `--check-llm` can print a sentence instead of a traceback. Only
    # openrouter has anything to say: its free model ids rotate, so there is no
    # safe default to fall back on.
    unmet = settings.model_requirement
    if unmet:
        raise LLMError(
            unmet,
            provider=settings.llm_provider,
            model="<unset>",
            hint="LLM_MODEL is read from .env or the process environment.",
        )

    system = f"{SYSTEM_PROMPT}\n\n{schema_prompt(schema)}"
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=settings.llm_timeout_seconds)
    assert client is not None

    user = prompt
    last_error = ""
    # Every provider call in this function is charged here, before the request,
    # so a retry for a truncated reply cannot slip past the count.
    budget = budget if budget is not None else CallBudget()

    try:
        total = 0.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            budget.take()
            _log(
                settings,
                "llm.request",
                provider=settings.llm_provider,
                model=settings.llm_model,
                attempt=attempt,
                prompt_chars=len(prompt),
                spent_ms=int(total * 1000),
            )
            started = time.monotonic()
            try:
                raw, usage = _complete(settings, client, system, user)
            except TruncatedReply as exc:
                # _complete already raised the token limit. Retrying the same
                # prompt with a bigger allowance is a different request, so it
                # costs nothing extra in correctness -- but it is still a live
                # call, so it is charged against the same attempt budget rather
                # than granting an extra one for free.
                last_error = str(exc)
                # Timed, because the truncated call is the slow one: it used the
                # whole token allowance before saying nothing. A log that only
                # recorded successful calls would make the 80-second run look
                # instant.
                spent = time.monotonic() - started
                total += spent
                _log(
                    settings,
                    "llm.truncated",
                    provider=settings.llm_provider,
                    attempt=attempt,
                    max_tokens=settings.llm_max_tokens,
                    elapsed_ms=int(spent * 1000),
                    total_ms=int(total * 1000),
                    error=last_error,
                )
                if attempt >= MAX_ATTEMPTS:
                    raise LLMError(
                        f"{settings.llm_provider} returned nothing usable in "
                        f"{MAX_ATTEMPTS} attempts even after raising the token "
                        f"limit to {settings.llm_max_tokens}: {last_error}. "
                        "Raise LLM_MAX_TOKENS in .env, or use a model that "
                        "answers without a long reasoning prefix.",
                        provider=settings.llm_provider,
                        model=str(settings.llm_model),
                    ) from exc
                continue
            except LLMError as exc:
                # The POST itself was timed and logged in _post, so the duration
                # of a rejected request is already on record. It still counts
                # against the wait the user sat through.
                total += time.monotonic() - started
                # A rejected request is not going to be accepted on the second
                # attempt, so it is raised rather than retried. Retrying it
                # would spend a call to reproduce the same error and report it
                # as "unparseable JSON" when the real cause was a 400.
                if not is_retryable_status(exc.status_code):
                    _log(
                        settings,
                        "llm.not_retried",
                        provider=settings.llm_provider,
                        status_code=exc.status_code,
                        elapsed_ms=int(total * 1000),
                        reason="4xx is not 429; the request is wrong, not unlucky",
                    )
                    raise
                last_error = exc.detail or str(exc)
                if attempt >= MAX_ATTEMPTS:
                    raise
                continue

            # Every completed call is timed, whether it turns out to be usable.
            # The wait the user sits through is the whole story: a run that took
            # 80 seconds across three truncated attempts looks identical, in the
            # status bar, to one that took 80 seconds of thinking.
            elapsed = time.monotonic() - started
            total += elapsed
            ms = int(elapsed * 1000)

            try:
                parsed = schema.model_validate_json(extract_json(raw))
            except (ValueError, ValidationError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                _log(
                    settings,
                    "llm.parse_failed",
                    provider=settings.llm_provider,
                    attempt=attempt,
                    elapsed_ms=ms,
                    error=last_error,
                    raw_excerpt=raw[:500],
                )
                if attempt < MAX_ATTEMPTS:
                    user = f"{prompt}\n\n{RETRY_HINT}"
                    continue
                raise LLMError(
                    f"{settings.llm_provider} returned unparseable/invalid JSON "
                    f"after {MAX_ATTEMPTS} attempts: {last_error}",
                    provider=settings.llm_provider,
                    model=str(settings.llm_model),
                    detail=raw[:500],
                ) from exc

            _log(
                settings,
                "llm.ok",
                provider=settings.llm_provider,
                attempt=attempt,
                model=settings.llm_model,
                elapsed_ms=ms,
                total_ms=int(total * 1000),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
            return parsed
    finally:
        if owns_client:
            client.close()

    raise LLMError(  # pragma: no cover - loop always returns or raises
        "unreachable",
        provider=settings.llm_provider,
        model=str(settings.llm_model),
        detail=last_error,
    )
