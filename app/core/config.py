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
    database_connect_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        description="Maximum time to wait while establishing a PostgreSQL connection.",
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

    runs_storage_dir: str = Field(
        default="storage/runs",
        description="Directory where each run's normalized dataset tables are written.",
    )
    runs_max_upload_bytes: int = Field(
        default=200 * 1024 * 1024,
        ge=1,
        description="Upper bound on the total size of one dataset upload.",
    )

    fraud_max_bytes_per_file: int = Field(
        default=50 * 1024 * 1024,
        ge=1,
        description="Upper bound on each CSV sent to POST /fraud/analyze.",
    )
    fraud_max_rows_per_table: int = Field(
        default=1_000_000,
        ge=1,
        description="Upper bound on rows per estate table the fraud engine loads.",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
