from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.db import Base

# BIGINT identity on Postgres. SQLite only auto-assigns rowids for a column declared
# exactly "INTEGER PRIMARY KEY" (which is 64-bit there anyway), so use that variant.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")

USERNAME_LENGTH = 32


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigIntPK, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(USERNAME_LENGTH), unique=True)
    # Lower-cased username: makes names unique case-insensitively.
    username_normalized: Mapped[str] = mapped_column(
        String(USERNAME_LENGTH), unique=True
    )
    # Only the password hash is ever stored, never the plain password.
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), server_default="player")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"User(user_id={self.user_id!r}, username={self.username!r})"
