"""Configuration loaded from environment / .env.

The provider is chosen with LLM_PROVIDER. gemini, groq and mistral all speak
the OpenAI chat-completions dialect, so llm.py keeps a single HTTP path for
them and a separate branch for anthropic.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["gemini", "groq", "mistral", "anthropic"]

PROVIDERS: tuple[Provider, ...] = ("gemini", "groq", "mistral", "anthropic")

# Used when neither .env nor the process environment names a provider.
DEFAULT_PROVIDER: Provider = "anthropic"

# Base URL of the OpenAI-compatible /chat/completions endpoint per provider.
OPENAI_COMPAT_BASE_URLS: dict[Provider, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
}

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"

# Defaults used when LLM_MODEL is not set.
DEFAULT_MODELS: dict[Provider, str] = {
    "gemini": "gemini-3.8-flash",
    "groq": "llama-3.3-70b-versatile",
    "mistral": "mistral-large-latest",
    "anthropic": "claude-sonnet-4-5",
}

# Env var holding the API key for each provider.
API_KEY_VARS: dict[Provider, str] = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


class ConfigError(RuntimeError):
    """Raised when the environment is not usable."""


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
        if self.llm_model is None:
            object.__setattr__(self, "llm_model", DEFAULT_MODELS[self.llm_provider])
        return self

    # --- derived values -------------------------------------------------

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
