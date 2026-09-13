"""Application settings, read from the environment (and `.env` in development)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql://infosys:infosys@localhost:5433/infosys",
        description="PostgreSQL DSN used by the API and the importer.",
    )
    database_pool_min_size: int = Field(default=1, ge=1)
    database_pool_max_size: int = Field(default=10, ge=1)

    blacklist_max_companies_per_request: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Upper bound on companies per check request, to cap request cost.",
    )
    blacklist_name_similarity_threshold: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        description="Minimum pg_trgm similarity for a fuzzy company-name match.",
    )

    auth_session_ttl_days: int = Field(
        default=7,
        ge=1,
        description="How long a session cookie stays valid after sign-in.",
    )
    auth_session_cookie_name: str = Field(default="infosys_session")
    auth_session_cookie_secure: bool = Field(
        default=False,
        description="Set the session cookie's Secure flag. Enable once served over HTTPS.",
    )
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="Origins allowed to call the API with credentials (the frontend's dev URL).",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
