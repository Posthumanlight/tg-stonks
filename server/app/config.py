"""Application settings, loaded from environment variables and the repo-root `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# server/app/config.py -> parents[2] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Any SQLAlchemy URL. Plain `postgresql://` URLs (as copied from Supabase)
    # are rewritten to the asyncpg driver by `normalize_db_url`.
    database_url: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
