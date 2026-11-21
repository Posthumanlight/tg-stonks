"""All ORM models. Import from here so `Base.metadata` sees every table (Alembic relies on it)."""

from app.persistence.models.user import User

__all__ = ["User"]
