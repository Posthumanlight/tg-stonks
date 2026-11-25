"""Combat records: enough to replay any fight exactly (docs/architecture.md
"Persistence and recovery"). Generated state is never stored — only setup, seed and
the actions."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.db import Base


class Combat(Base):
    __tablename__ = "combats"

    combat_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(String(16))  # hotseat (PvP later)
    status: Mapped[str] = mapped_column(String(16), index=True)
    worker_slot: Mapped[int] = mapped_column(Integer)
    setup: Mapped[dict[str, Any]] = mapped_column(JSON)
    seed: Mapped[int] = mapped_column(BigInteger)
    content_hash: Mapped[str] = mapped_column(String(64))
    rules_version: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CombatAction(Base):
    __tablename__ = "combat_actions"

    combat_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("combats.combat_id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)  # action number, from 0
    action: Mapped[dict[str, Any]] = mapped_column(JSON)
