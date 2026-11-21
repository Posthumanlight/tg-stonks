"""World-gen deltas and pins. Generated data itself is never stored (docs/world-gen.md)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.db import Base
from app.persistence.models.user import BigIntPK

# Object paths are short ("s/17/p/2", later region paths); 128 leaves room.
PATH_LENGTH = 128


class World(Base):
    """The persistent world: its seed and the galaxy generator version it is pinned to."""

    __tablename__ = "worlds"

    world_id: Mapped[int] = mapped_column(BigIntPK, Identity(), primary_key=True)
    seed: Mapped[int] = mapped_column(BigInteger)
    galaxy_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WorldgenPin(Base):
    """An object locked to a generator version because a delta touches it."""

    __tablename__ = "worldgen_pins"

    object_path: Mapped[str] = mapped_column(String(PATH_LENGTH), primary_key=True)
    generator: Mapped[str] = mapped_column(String(32), primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    pinned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BodyName(Base):
    """Custom display name of a generated body (a delta). No API yet: set in the DB."""

    __tablename__ = "body_names"

    object_path: Mapped[str] = mapped_column(String(PATH_LENGTH), primary_key=True)
    custom_name: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
