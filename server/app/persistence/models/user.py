from sqlalchemy import BigInteger, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.db import Base

# BIGINT identity on Postgres. SQLite only auto-assigns rowids for a column declared
# exactly "INTEGER PRIMARY KEY" (which is 64-bit there anyway), so use that variant.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigIntPK, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    # Only the password hash is ever stored, never the plain password.
    hashed_password: Mapped[str] = mapped_column(String(255))

    def __repr__(self) -> str:
        return f"User(user_id={self.user_id!r}, username={self.username!r})"
