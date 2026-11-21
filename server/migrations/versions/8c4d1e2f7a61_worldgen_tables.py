"""worldgen tables: worlds, worldgen_pins, body_names

Revision ID: 8c4d1e2f7a61
Revises: 5f1c2a7e9b30
Create Date: 2026-11-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c4d1e2f7a61"
down_revision: Union[str, Sequence[str], None] = "5f1c2a7e9b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worlds",
        sa.Column(
            "world_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("galaxy_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("world_id", name=op.f("pk_worlds")),
    )
    op.create_table(
        "worldgen_pins",
        sa.Column("object_path", sa.String(length=128), nullable=False),
        sa.Column("generator", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "pinned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "object_path", "generator", name=op.f("pk_worldgen_pins")
        ),
    )
    op.create_table(
        "body_names",
        sa.Column("object_path", sa.String(length=128), nullable=False),
        sa.Column("custom_name", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("object_path", name=op.f("pk_body_names")),
    )


def downgrade() -> None:
    op.drop_table("body_names")
    op.drop_table("worldgen_pins")
    op.drop_table("worlds")
