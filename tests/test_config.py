"""Config: provider selection, per-provider keys, defaults."""

from __future__ import annotations

import pytest

from app.config import (
    ANTHROPIC_BASE_URL,
    API_KEY_VARS,
    DEFAULT_MODELS,
    OPENAI_COMPAT_BASE_URLS,
    PROVIDERS,
    ConfigError,
    Settings,
)


def test_provider_union_is_exactly_the_four() -> None:
    assert PROVIDERS == ("gemini", "groq", "mistral", "anthropic")


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(Exception) as exc:
        Settings(llm_provider="openai", _env_file=None)
    assert "llm_provider" in str(exc.value)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_default_model_fills_in(provider: str) -> None:
    s = Settings(llm_provider=provider, _env_file=None)
    assert s.llm_model == DEFAULT_MODELS[provider]


@pytest.mark.parametrize("provider", ["gemini", "groq", "mistral"])
def test_openai_compat_base_urls(provider: str) -> None:
    s = Settings(llm_provider=provider, _env_file=None)
    assert s.base_url == OPENAI_COMPAT_BASE_URLS[provider]
    assert s.base_url.startswith("https://")


def test_anthropic_base_url() -> None:
    s = Settings(llm_provider="anthropic", _env_file=None)
    assert s.base_url == ANTHROPIC_BASE_URL


@pytest.mark.parametrize("provider", PROVIDERS)
def test_api_key_reads_its_own_var(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_VARS[provider], "key-123")
    for other in PROVIDERS:
        if other != provider:
            monkeypatch.delenv(API_KEY_VARS[other], raising=False)
    assert Settings(llm_provider=provider, _env_file=None).api_key == "key-123"


def test_api_key_absent_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in API_KEY_VARS.values():
        monkeypatch.delenv(var, raising=False)
    assert Settings(llm_provider="groq", _env_file=None).api_key is None


def test_default_provider_is_anthropic() -> None:
    assert Settings(_env_file=None).llm_provider == "anthropic"


def test_config_error_is_exported() -> None:
    assert issubclass(ConfigError, RuntimeError)
