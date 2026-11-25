"""Application settings, loaded from environment variables and the repo-root `.env`.

The full list of keys is in docs/architecture.md ("Configuration and secrets").
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_AUTH_SECRET_BYTES = 32

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

    # --- auth (docs/architecture.md "Authentication") ---------------------------------
    auth_secret: SecretStr | None = None  # HS256 key; required by the gateway
    auth_secret_previous: SecretStr | None = None  # still verifies during rotation
    auth_access_ttl_s: int = Field(default=900, ge=60)
    auth_refresh_ttl_s: int = Field(default=30 * 24 * 3600, ge=3600)
    auth_cookie_secure: bool = True

    # --- processes and pools ----------------------------------------------------------
    combat_workers: int | None = Field(default=None, ge=1)  # None: CPU cores - 1
    combat_idle_timeout_s: int = Field(default=24 * 3600, ge=60)
    combat_flush_interval_s: float = Field(default=1.0, gt=0)
    db_pool_gateway: int = Field(default=5, ge=1)
    db_pool_worker: int = Field(default=2, ge=1)

    @property
    def combat_worker_count(self) -> int:
        if self.combat_workers is not None:
            return self.combat_workers
        return max(1, (os.cpu_count() or 2) - 1)

    def require_auth_secret(self) -> bytes:
        return _secret_bytes(self.auth_secret, "AUTH_SECRET")

    def previous_auth_secret(self) -> bytes | None:
        if self.auth_secret_previous is None:
            return None
        return _secret_bytes(self.auth_secret_previous, "AUTH_SECRET_PREVIOUS")

    def require_world_seed(self) -> int:
        if self.world_seed is None:
            raise RuntimeError(
                "WORLD_SEED is not set: add WORLD_SEED=<int 0..2^63-1> to .env "
                "(docs/world-gen.md, 'World seed')"
            )
        return self.world_seed


def _secret_bytes(secret: SecretStr | None, name: str) -> bytes:
    value = secret.get_secret_value().encode() if secret is not None else b""
    if len(value) < MIN_AUTH_SECRET_BYTES:
        raise RuntimeError(
            f"{name} must be set to at least {MIN_AUTH_SECRET_BYTES} random bytes "
            '(e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`)'
        )
    return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
