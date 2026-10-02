"""--check-llm: pass/fail reporting per provider, HTTP mocked."""

from __future__ import annotations

import json

import httpx
import pytest

from app import cli
from tests.fakes import FakeClient


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


@pytest.mark.parametrize("provider", ["gemini", "groq", "mistral", "anthropic"])
def test_check_llm_passes_for_each_provider(
    provider: str, monkeypatch: pytest.MonkeyPatch, fake_transport, capsys
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "test-key")
    client = fake_transport(_ok_reply())

    from app import config

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
    assert "FAIL" in capsys.readouterr().out


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


def test_cli_prints_help_without_flags(capsys) -> None:
    assert cli.main([]) == 0
    assert "--check-llm" in capsys.readouterr().out


def test_cli_list_providers(capsys) -> None:
    assert cli.main(["--list-providers"]) == 0
    out = capsys.readouterr().out
    for provider in ("gemini", "groq", "mistral", "anthropic"):
        assert provider in out
