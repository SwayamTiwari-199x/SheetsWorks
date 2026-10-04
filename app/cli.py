"""CLI: ``python -m app.cli --check-llm``.

Sends a tiny JSON-schema request to the configured provider and reports
whether the round trip worked. Requires a real API key (it makes a live call);
the test suite exercises the same code path with a mocked transport.
"""

from __future__ import annotations

import argparse
import sys

from pydantic import BaseModel, Field

from .config import API_KEY_VARS, PROVIDERS, REQUIRES_EXPLICIT_MODEL, get_settings
from .llm import LLMError, ask


class PingOut(BaseModel):
    """Deliberately tiny schema: one required string."""

    answer: str = Field(description="The single word you were asked for")
    ok: bool = Field(description="True when the call succeeded")


def run_check() -> int:
    settings = get_settings()
    provider = settings.llm_provider
    key_var = API_KEY_VARS[provider]

    print(f"provider : {provider}")
    print(f"model    : {settings.llm_model or '(not set)'}")
    print(f"base url : {settings.base_url}")
    print(f"key var  : {key_var}")

    # Checked before the key: a missing model means nothing can be sent at all,
    # so reporting "your API key is not set" first would send the user after the
    # wrong problem.
    unmet = settings.model_requirement
    if unmet:
        print(f"result   : FAIL - {unmet}")
        return 1

    if not settings.api_key:
        print(f"result   : FAIL - {key_var} is not set")
        print(f"           add {key_var}=... to .env, then re-run")
        return 1

    try:
        out = ask(PingOut, "Reply with answer='pong' and ok=true.")
    except LLMError as exc:
        print(f"result   : FAIL")
        for line in exc.report().splitlines():
            print(f"           {line}")
        return 1
    except Exception as exc:  # network, DNS, TLS, ...
        print(f"result   : FAIL - {type(exc).__name__}: {exc}")
        return 1

    if out.answer.strip().lower() != "pong" or not out.ok:
        print(f"result   : FAIL - schema validated but content was wrong: {out}")
        return 1

    print(f"result   : PASS - {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="Resume Builder utilities")
    parser.add_argument(
        "--check-llm",
        action="store_true",
        help="send a tiny JSON-schema test to the configured LLM provider",
    )
    parser.add_argument(
        "--list-providers",
        action="store_true",
        help="print supported LLM_PROVIDER values and exit",
    )
    args = parser.parse_args(argv)

    if args.list_providers:
        print("supported LLM_PROVIDER values:")
        for p in PROVIDERS:
            note = "  (LLM_MODEL required)" if p in REQUIRES_EXPLICIT_MODEL else ""
            print(f"  {p:<10} key var: {API_KEY_VARS[p]}{note}")
        return 0

    if args.check_llm:
        return run_check()

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
