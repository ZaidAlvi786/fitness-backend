"""Typed, validated application settings (pydantic-settings).

Loaded once at startup; missing/invalid required values raise immediately so the process fails fast
rather than deep inside the first request. No secrets have defaults.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    development = "development"
    staging = "staging"
    production = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = Environment.development
    log_level: str = "INFO"

    # --- Supabase ---
    supabase_url: str = Field(..., description="Supabase project URL, e.g. https://ref.supabase.co")
    supabase_jwt_audience: str = "authenticated"

    # Async SQLAlchemy DSN (postgresql+asyncpg://...) to the same Postgres.
    database_url: str = Field(..., description="Async Postgres DSN for SQLAlchemy/asyncpg")

    # --- LLM provider (Google Gemini via Vertex AI Express — server-side only) ---
    gemini_api_key: str = Field(..., description="Vertex AI Express API key (AQ.-prefixed) — server-side secret")
    gemini_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: float = 30.0
    llm_max_tokens: int = 1024

    # --- Cost control ---
    coaching_rate_limit_per_hour: int = 10

    # --- CORS (comma-separated string in env → list) ---
    cors_origins: list[str] = Field(default_factory=list)

    # --- Observability ---
    sentry_dsn: str | None = None

    @field_validator("supabase_url")
    @classmethod
    def _no_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def jwks_url(self) -> str:
        """Supabase JWKS endpoint for asymmetric (RS256) signing keys."""
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url}/auth/v1"

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.production


@lru_cache
def get_settings() -> Settings:
    """Singleton settings. `lru_cache` so the env is read and validated exactly once."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment/.env
