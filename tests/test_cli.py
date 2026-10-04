"""--check-llm: pass/fail reporting per provider, HTTP mocked."""

from __future__ import annotations

import json

import httpx
import pytest

from app import cli
from app.config import API_KEY_VARS, PROVIDERS, REQUIRES_EXPLICIT_MODEL
from tests.fakes import FakeClient

# An arbitrary model id, needed for the providers that have no default.
MODEL = "test-vendor/test-model:free"


@pytest.fixture
def fake_transport(monkeypatch: pytest.MonkeyPatch):
    """Patch httpx.Client so any call inside the CLI hits our fake."""

    def _install(replies: list[str], status_code: int = 200) -> FakeClient:
        client = FakeClient(replies=replies, status_code=status_code)
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: client)
        return client

    return _install


def _ok_reply() -> list[str]:
    return [json.dumps({"answer": "pong", "ok": True})]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_check_llm_passes_for_each_provider(
    provider: str, monkeypatch: pytest.MonkeyPatch, fake_transport, capsys
) -> None:
    from app import config

    monkeypatch.setenv("LLM_PROVIDER", provider)
    # From API_KEY_VARS, not provider.upper(): the two agree today by luck, and
    # would stop agreeing the moment a provider's key var did not end in
    # _API_KEY.
    monkeypatch.setenv(API_KEY_VARS[provider], "test-key")
    if provider in REQUIRES_EXPLICIT_MODEL:
        monkeypatch.setenv("LLM_MODEL", MODEL)
    client = fake_transport(_ok_reply())

    config.get_settings.cache_clear()
    assert cli.run_check() == 0

    out = capsys.readouterr().out
    assert "PASS" in out
    assert provider in out
    assert client.call_count == 1


def test_check_llm_fails_without_api_key(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from app import config

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    config.get_settings.cache_clear()

    assert cli.run_check() == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "GROQ_API_KEY" in out


def test_check_llm_fails_on_bad_json(
    monkeypatch: pytest.MonkeyPatch, fake_transport, capsys
) -> None:
    from app import config

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = fake_transport(["this is not json"])

    config.get_settings.cache_clear()
    assert cli.run_check() == 1

    out = capsys.readouterr().out
    assert "FAIL" in out
    # still one retry happened before giving up
    assert client.call_count == 2


def test_check_llm_fails_on_http_error(
    monkeypatch: pytest.MonkeyPatch, fake_transport, capsys
) -> None:
    from app import config

    monkeypatch.setenv("LLM_PROVIDER", "mistral")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    fake_transport(["nope"], status_code=401)

    config.get_settings.cache_clear()
    assert cli.run_check() == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "HTTP 401" in out
    assert "hint:" in out


def test_check_llm_fails_on_wrong_content(
    monkeypatch: pytest.MonkeyPatch, fake_transport, capsys
) -> None:
    from app import config

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_transport([json.dumps({"answer": "banana", "ok": True})])

    config.get_settings.cache_clear()
    assert cli.run_check() == 1
    assert "FAIL" in capsys.readouterr().out


def test_check_llm_fails_when_openrouter_has_no_model(
    monkeypatch: pytest.MonkeyPatch, fake_transport, capsys
) -> None:
    """The requirement, at the CLI.

    Must be reported *before* the API key, because a missing model means nothing
    can be sent at all -- telling the user their key is missing would send them
    after the wrong problem. The key is set here deliberately, so if the model
    check were ordered second this test could not distinguish the two failures.
    """
    from app import config

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    client = fake_transport(_ok_reply())

    config.get_settings.cache_clear()
    assert cli.run_check() == 1

    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "LLM_MODEL" in out
    assert "https://openrouter.ai/models" in out
    assert "OPENROUTER_API_KEY is not set" not in out, (
        "the key is present here, so a key complaint would be the wrong answer"
    )
    assert client.call_count == 0, "nothing may be sent without a model"
    assert "model    : (not set)" in out, (
        "the summary must not print 'model: None' as if it were a value"
    )


def test_check_llm_passes_for_openrouter_once_a_model_is_set(
    monkeypatch: pytest.MonkeyPatch, fake_transport, capsys
) -> None:
    from app import config

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", MODEL)
    client = fake_transport(_ok_reply())

    config.get_settings.cache_clear()
    assert cli.run_check() == 0
    out = capsys.readouterr().out
    assert MODEL in out, "the chosen model must be reported back"
    assert "https://openrouter.ai/api/v1" in out
    assert client.call_count == 1
    assert client.calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"


def test_cli_prints_help_without_flags(capsys) -> None:
    assert cli.main([]) == 0
    assert "--check-llm" in capsys.readouterr().out


def test_cli_list_providers(capsys) -> None:
    assert cli.main(["--list-providers"]) == 0
    out = capsys.readouterr().out
    for provider in PROVIDERS:
        assert provider in out, f"{provider} is missing from --list-providers"
    # The exception has to be discoverable from the list, or it is a trap.
    line = next(ln for ln in out.splitlines() if "openrouter" in ln)
    assert "LLM_MODEL required" in line, line
    # And it must not be claimed for the providers that do have defaults.
    for provider in set(PROVIDERS) - set(REQUIRES_EXPLICIT_MODEL):
        line = next(ln for ln in out.splitlines() if provider in ln)
        assert "LLM_MODEL required" not in line, line
