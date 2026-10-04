"""Config: provider selection, per-provider keys, defaults."""

from __future__ import annotations

import pytest

from app.config import (
    ANTHROPIC_BASE_URL,
    API_KEY_VARS,
    DEFAULT_MODELS,
    DEFAULT_PROVIDER,
    OPENAI_COMPAT_BASE_URLS,
    PROVIDERS,
    REQUIRES_EXPLICIT_MODEL,
    Settings,
)


def test_provider_union_is_exactly_the_five() -> None:
    assert PROVIDERS == ("gemini", "groq", "mistral", "anthropic", "openrouter")


def test_every_provider_has_a_key_var_a_base_url_and_a_kind() -> None:
    """The three dicts and the union must agree, or a provider can be selected
    that config cannot describe."""
    assert set(API_KEY_VARS) == set(PROVIDERS)
    assert set(API_KEY_VARS) == set(OPENAI_COMPAT_BASE_URLS) | {"anthropic"}
    assert DEFAULT_MODELS.keys() | REQUIRES_EXPLICIT_MODEL == set(PROVIDERS)
    assert not (DEFAULT_MODELS.keys() & REQUIRES_EXPLICIT_MODEL), (
        "a provider cannot both require an explicit model and have a default"
    )


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(Exception) as exc:
        Settings(llm_provider="openai", _env_file=None)
    assert "llm_provider" in str(exc.value)


@pytest.mark.parametrize("provider", sorted(DEFAULT_MODELS))
def test_default_model_fills_in(provider: str) -> None:
    s = Settings(llm_provider=provider, _env_file=None)
    assert s.llm_model == DEFAULT_MODELS[provider]


@pytest.mark.parametrize("provider", sorted(OPENAI_COMPAT_BASE_URLS))
def test_openai_compat_base_urls(provider: str) -> None:
    s = Settings(llm_provider=provider, _env_file=None)
    assert s.base_url == OPENAI_COMPAT_BASE_URLS[provider]
    assert s.base_url.startswith("https://")
    assert not s.base_url.endswith("/"), "a trailing slash would double up on /chat/completions"


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
    assert Settings(_env_file=None).llm_provider == DEFAULT_PROVIDER == "anthropic"


# --- openrouter: the provider with no default model ----------------------


def test_openrouter_has_no_default_model() -> None:
    """The whole point of the exception.

    OpenRouter's free tier rotates model ids -- ":free" variants are pulled and
    added without notice. A hardcoded default would be wrong within days and
    would then fail as an opaque 404 from a provider that names the model as the
    problem, long after the mistake was made here.
    """
    assert "openrouter" in REQUIRES_EXPLICIT_MODEL
    assert "openrouter" not in DEFAULT_MODELS
    s = Settings(llm_provider="openrouter", _env_file=None)
    assert s.llm_model is None, "nothing may be filled in on its behalf"


def test_openrouter_still_builds_without_a_model() -> None:
    """Deliberate. If Settings refused to construct, `--check-llm` would die with
    a pydantic traceback instead of printing what to set, and there would be no
    way to inspect the rest of the configuration to find out what is wrong."""
    s = Settings(llm_provider="openrouter", _env_file=None)
    assert s.llm_provider == "openrouter"
    assert s.base_url == "https://openrouter.ai/api/v1"
    assert s.api_key is None


def test_openrouter_requires_an_explicit_model_and_says_how_to_fix_it() -> None:
    s = Settings(llm_provider="openrouter", _env_file=None)
    problem = s.model_requirement
    assert problem, "a missing model must be reported, not silently defaulted"
    assert "LLM_MODEL" in problem, "the message must name the variable to set"
    assert "openrouter" in problem, "and the provider, so it is unambiguous"
    assert "https://openrouter.ai/models" in problem, (
        "and somewhere to find a model id, since none is offered"
    )


@pytest.mark.parametrize("model", [
    "meta-llama/llama-3.3-70b-instruct:free",
    "some-org/some-model",          # no :free suffix
    "vendor/model:free",            # :free in a different position
])
def test_any_explicit_model_satisfies_openrouter(model: str) -> None:
    """No allowlist and no shape check on the model id.

    Tempting as it is to validate that the id looks like `vendor/model`, the ids
    do not follow a rule this app could keep up with -- they change when the
    provider changes its catalogue. The provider is the authority on which ids
    exist; the app's only job is not to invent one.
    """
    s = Settings(llm_provider="openrouter", llm_model=model, _env_file=None)
    assert s.model_requirement == ""
    assert s.llm_model == model


def test_openrouter_rejects_a_blank_model() -> None:
    """`LLM_MODEL=` in .env sets it to an empty string, not to None, so the
    validator's `is None` check does not catch it. Whitespace only counts too --
    it would be sent as the model id and rejected as an unknown model."""
    for blank in ("", "   ", "\t"):
        s = Settings(llm_provider="openrouter", llm_model=blank, _env_file=None)
        assert s.model_requirement, f"{blank!r} must not pass as a model"


def test_every_provider_key_is_scrubbed_from_the_test_environment() -> None:
    """Regression, and it leaked a real secret.

    `tests/conftest.py` listed the API key vars twice, by hand. openrouter was
    added to `API_KEY_VARS` and to neither, so a developer's real
    `OPENROUTER_API_KEY` was visible to the suite -- and a test asserting
    `settings.api_key is None` failed with the key printed in the assertion
    message.

    Deriving one list from `API_KEY_VARS` fixes the live case; this test is what
    stops the other list rotting in the same way again.
    """
    from tests import conftest

    assert set(API_KEY_VARS.values()) <= set(conftest._PRE_IMPORT_SCRUB), (
        "a provider key is missing from the pre-import scrub in conftest.py"
    )
    assert set(API_KEY_VARS.values()) <= set(conftest._LLM_ENV_VARS), (
        "a provider key is missing from the per-test scrub in conftest.py"
    )


def test_the_autouse_fixture_clears_an_ambient_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same leak, proven from the other direction.

    Sets a key, runs the scrub, and checks it is gone. This is what actually
    failed in practice: a developer's real `OPENROUTER_API_KEY` was visible to the
    suite, so `assert settings.api_key is None` printed the key in its own failure
    message.

    Calls `scrub_llm_env` directly rather than the fixture, because pytest refuses
    direct fixture calls -- and the alternative, asserting that a list contains a
    string, would have passed while the leak was still happening.
    """
    import os

    from tests import conftest

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-should-never-be-here")
    assert os.getenv("OPENROUTER_API_KEY"), "precondition: the key is set"

    conftest.scrub_llm_env(monkeypatch)

    assert os.getenv("OPENROUTER_API_KEY") is None, (
        "the scrub did not remove an ambient provider key"
    )


@pytest.mark.parametrize("provider", ["gemini", "groq", "mistral", "anthropic"])
def test_the_other_providers_say_nothing_about_their_model(provider: str) -> None:
    """`model_requirement` exists for openrouter. Every other provider must be
    untouched by it, or this would have quietly changed their behaviour."""
    s = Settings(llm_provider=provider, _env_file=None)
    assert s.model_requirement == ""


def test_default_provider_ignores_ambient_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: process env wins over .env and _env_file=None cannot stop it.

    A stray LLM_PROVIDER in the shell used to make this suite fail on one
    machine and pass on another.
    """
    monkeypatch.setenv("LLM_PROVIDER", "mistral")
    assert Settings(_env_file=None).llm_provider == "mistral"


def test_conftest_scrubs_ambient_llm_env() -> None:
    """The autouse isolated_llm_env fixture must keep LLM vars out of tests."""
    import os

    for var in ("LLM_PROVIDER", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        assert var not in os.environ, f"{var} leaked into the test process"


def test_real_env_is_not_read_by_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with the repo's .env present, tests must resolve to the default."""
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("LLM_PROVIDER")
    assert Settings(_env_file=None).llm_provider == DEFAULT_PROVIDER