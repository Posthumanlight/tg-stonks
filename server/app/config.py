"""Application settings, loaded from environment variables and the repo-root `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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

    # Seed of the one persistent galaxy (docs/world-gen.md). Optional here so tools like
    # Alembic run without it; code that generates the world calls `require_world_seed()`.
    # Bounded to fit a signed BIGINT column.
    world_seed: int | None = Field(default=None, ge=0, le=2**63 - 1)

    def require_world_seed(self) -> int:
        if self.world_seed is None:
            raise RuntimeError(
                "WORLD_SEED is not set: add WORLD_SEED=<int 0..2^63-1> to .env "
                "(docs/world-gen.md, 'World seed')"
            )
        return self.world_seed


@lru_cache
def get_settings() -> Settings:
    return Settings()
