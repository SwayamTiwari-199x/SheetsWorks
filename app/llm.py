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

- gemini, groq, mistral -> one OpenAI-compatible ``/chat/completions`` path.
- anthropic -> a separate branch (``/messages``).

The reply is then extracted, ``json.loads``-ed, and validated with pydantic.
A failure at any of those steps triggers **exactly one retry**; a second
failure raises :class:`LLMError`.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import PROVIDERS, Settings, get_settings

logger = logging.getLogger("app.llm")

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 2  # first try + one retry

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


def _http_error(
    exc: Exception, settings: Settings, status_code: int
) -> LLMError:
    """Translate an httpx failure into an actionable LLMError."""
    message = ""
    detail = ""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            detail = _extract_error_message(response.json())
        except Exception:
            try:
                detail = response.text[:300]
            except Exception:
                detail = ""
        message = f"HTTP {status_code} from {settings.llm_provider}"
    else:
        message = f"{type(exc).__name__}: {exc}"
        detail = str(exc)[:300]

    return LLMError(
        message,
        provider=settings.llm_provider,
        model=str(settings.llm_model),
        detail=detail,
        status_code=status_code,
        hint=_STATUS_HINTS.get(status_code, ""),
    )


def schema_prompt(schema: type[BaseModel]) -> str:
    """Render a pydantic model's JSON schema as prompt text."""
    return SCHEMA_INSTRUCTION.format(schema=json.dumps(schema.model_json_schema(), indent=2))


def _setup_logging(settings: Settings) -> None:
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(settings.log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    if not any(getattr(h, "_resume_builder", False) for h in logger.handlers):
        handler._resume_builder = True  # type: ignore[attr-defined]
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


def _post_openai_compat(
    settings: Settings, client: httpx.Client, system: str, user: str
) -> str:
    """gemini / groq / mistral: OpenAI chat-completions dialect."""
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
    return resp.json()["choices"][0]["message"]["content"]


def _post_anthropic(
    settings: Settings, client: httpx.Client, system: str, user: str
) -> str:
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
    blocks = resp.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _post(
    client: httpx.Client, url: str, settings: Settings, *, headers: dict, body: dict
):
    """POST and convert transport/HTTP failures into LLMError.

    Credentials are never put in an error message: only the status code and
    whatever text the provider chose to send back are surfaced.
    """
    try:
        resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        return resp
    except httpx.HTTPStatusError as exc:
        raise _http_error(exc, settings, exc.response.status_code) from None
    except httpx.HTTPError as exc:
        raise _http_error(exc, settings, 0) from None


def _complete(settings: Settings, client: httpx.Client, system: str, user: str) -> str:
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
) -> T:
    """Send ``prompt`` to the configured provider, return ``schema``-validated output.

    Retries once on invalid JSON or validation failure, then raises LLMError.
    """
    settings = settings or get_settings()
    if settings.llm_provider not in PROVIDERS:
        raise LLMError(
            f"unknown provider {settings.llm_provider!r}",
            provider=str(settings.llm_provider),
            model=str(settings.llm_model),
        )

    system = f"{SYSTEM_PROMPT}\n\n{schema_prompt(schema)}"
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=settings.llm_timeout_seconds)
    assert client is not None

    user = prompt
    last_error = ""

    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            _log(
                settings,
                "llm.request",
                provider=settings.llm_provider,
                model=settings.llm_model,
                attempt=attempt,
                prompt_chars=len(prompt),
            )
            raw = _complete(settings, client, system, user)

            try:
                parsed = schema.model_validate_json(extract_json(raw))
            except (ValueError, ValidationError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                _log(
                    settings,
                    "llm.parse_failed",
                    provider=settings.llm_provider,
                    attempt=attempt,
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
