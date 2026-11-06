"""Application settings, loaded from environment variables / ``.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All runtime configuration. Secrets come only from the environment / ``.env``."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_name: str = "ISRO Assistant API"
    app_env: str = "development"

    # PostgreSQL (SQLAlchemy URL with the psycopg async driver)
    database_url: str = "postgresql+psycopg://isro:isro_dev_password@localhost:5432/isro_agent"
    # Redis: token store, caches, run locks, WebSocket pub/sub
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480        # 8 hours
    refresh_token_days: int = 7

    cors_origins: Annotated[list[str], NoDecode] = []   # comma-separated in .env
    # admin accounts (comma-separated). Reserved: public registration refuses them; create with
    # `uv run python scripts/create_admin.py`.
    admin_emails: Annotated[list[str], NoDecode] = []
    admin_cache_ttl_s: int = 60
    agent_enabled: bool = True             # start the LangGraph agent (off for API-only tests)
    ws_auth_timeout_s: float = 10.0
    run_lock_ttl_s: int = 900              # max duration of one run (per-thread lock)
    usage_cache_ttl_s: int = 60
    user_cache_ttl_s: int = 300

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        return [o.strip() for o in v.split(",") if o.strip()] if isinstance(v, str) else v

    @field_validator("admin_emails", mode="before")
    @classmethod
    def _split_admins(cls, v):
        items = v.split(",") if isinstance(v, str) else (v or [])
        return [e.strip().lower() for e in items if e.strip()]

    def is_admin_email(self, email: str) -> bool:
        return email.strip().lower() in self.admin_emails

    @property
    def agent_database_url(self) -> str:
        """Plain libpq URL for the orchestrator's psycopg pool (no SQLAlchemy driver suffix)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
