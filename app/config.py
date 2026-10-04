"""Configuration loaded from environment / .env.

The provider is chosen with LLM_PROVIDER. gemini, groq, mistral and openrouter
all speak the OpenAI chat-completions dialect, so llm.py keeps a single HTTP path
for them and a separate branch for anthropic.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["gemini", "groq", "mistral", "anthropic", "openrouter"]

PROVIDERS: tuple[Provider, ...] = ("gemini", "groq", "mistral", "anthropic", "openrouter")

# Used when neither .env nor the process environment names a provider.
DEFAULT_PROVIDER: Provider = "anthropic"

# Base URL of the OpenAI-compatible /chat/completions endpoint per provider.
OPENAI_COMPAT_BASE_URLS: dict[Provider, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"

# Defaults used when LLM_MODEL is not set.
#
# openrouter is deliberately absent. Its free tier rotates model ids -- ":free"
# variants are pulled and added without notice -- so anything hardcoded here would
# be wrong within days, and a stale default then fails as an opaque 404 long
# after the mistake. See REQUIRES_EXPLICIT_MODEL.
DEFAULT_MODELS: dict[Provider, str] = {
    "gemini": "gemini-3.8-flash",
    "groq": "llama-3.3-70b-versatile",
    "mistral": "mistral-large-latest",
    "anthropic": "claude-sonnet-4-5",
}

# Providers that have no default model, so LLM_MODEL must be set explicitly.
REQUIRES_EXPLICIT_MODEL: frozenset[Provider] = frozenset({"openrouter"})

EXPLICIT_MODEL_REQUIRED = (
    "LLM_MODEL is required for {provider}: it has no default model. Free model "
    "ids on this provider rotate, so there is nothing safe to hardcode. Set "
    "LLM_MODEL=<model id> in .env -- the current list is at "
    "https://openrouter.ai/models"
)

# Env var holding the API key for each provider.
API_KEY_VARS: dict[Provider, str] = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: Provider = DEFAULT_PROVIDER
    llm_model: str | None = None
    llm_timeout_seconds: float = 60.0
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.2

    database_url: str = "sqlite:///./resume.db"
    log_dir: str = "logs"

    @model_validator(mode="after")
    def _fill_defaults(self) -> "Settings":
        # Providers in REQUIRES_EXPLICIT_MODEL are left with llm_model = None on
        # purpose, so Settings still *constructs* and --check-llm can print a
        # sentence about what to set. Raising here instead would turn a
        # one-line misconfiguration into a pydantic ValidationError traceback
        # from get_settings(), which is the opposite of a clear error.
        if self.llm_model is None and self.llm_provider not in REQUIRES_EXPLICIT_MODEL:
            object.__setattr__(self, "llm_model", DEFAULT_MODELS[self.llm_provider])
        return self

    # --- derived values -------------------------------------------------

    @property
    def model_requirement(self) -> str:
        """Why this configuration cannot run a request, or '' if it can.

        Only the providers in REQUIRES_EXPLICIT_MODEL have anything to say. A
        single message lives here so `llm.ask` and `--check-llm` cannot drift
        into telling the user two different things about the same mistake.
        """
        if self.llm_model and self.llm_model.strip():
            return ""
        if self.llm_provider in REQUIRES_EXPLICIT_MODEL:
            return EXPLICIT_MODEL_REQUIRED.format(provider=self.llm_provider)
        return ""

    @property
    def api_key(self) -> str | None:
        """Key for the selected provider, read from its dedicated env var."""
        import os

        return os.getenv(API_KEY_VARS[self.llm_provider]) or None

    @property
    def base_url(self) -> str:
        if self.llm_provider == "anthropic":
            return ANTHROPIC_BASE_URL
        return OPENAI_COMPAT_BASE_URLS[self.llm_provider]

    @property
    def log_path(self) -> str:
        return f"{self.log_dir}/llm.log"


@lru_cache
def get_settings() -> Settings:
    return Settings()
