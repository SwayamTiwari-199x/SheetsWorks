"""A minimal fake httpx.Client.

Used instead of respx so the test suite has no extra dependency and so we can
assert *how many* HTTP calls a code path makes (the retry-once contract).

Program a list of reply bodies; each call consumes one. Once exhausted the
last body repeats, which is what makes "retry once, then raise" observable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


@dataclass
class FakeClient:
    """Mimics httpx.Client enough for app.llm."""

    replies: list[str] = field(default_factory=list)
    status_code: int = 200
    calls: list[dict[str, Any]] = field(default_factory=list)
    closed: bool = False

    def post(self, url: str, *, headers: dict, json: dict) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})

        idx = min(len(self.calls) - 1, len(self.replies) - 1)
        text = self.replies[idx] if self.replies else "{}"

        if "/messages" in url:  # anthropic branch
            payload: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
        else:  # openai-compatible branch
            payload = {"choices": [{"message": {"role": "assistant", "content": text}}]}

        return FakeResponse(payload, self.status_code)

    def close(self) -> None:
        self.closed = True

    # --- convenience for assertions ------------------------------------

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_user_message(self) -> str:
        messages = self.calls[-1]["json"].get("messages", [])
        return messages[-1]["content"]

    @property
    def system_message(self) -> str:
        if "system" in self.calls[-1]["json"]:
            return self.calls[-1]["json"]["system"]
        return self.calls[-1]["json"]["messages"][0]["content"]
