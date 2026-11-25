"""combats + combat_actions (replayable combat records); RLS on Postgres

Revision ID: c7a2f0d58e14
Revises: b3d9e6a41c27
Create Date: 2026-11-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a2f0d58e14"
down_revision: Union[str, Sequence[str], None] = "b3d9e6a41c27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("combats", "combat_actions")


def _set_rls(enabled: bool) -> None:
    # Postgres-only (the documented rule-10 exception, see b3d9e6a41c27_auth_and_rls).
    if op.get_bind().dialect.name != "postgresql":
        return
    verb = "ENABLE" if enabled else "DISABLE"
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} {verb} ROW LEVEL SECURITY")


def upgrade() -> None:
    op.create_table(
        "combats",
        sa.Column("combat_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("worker_slot", sa.Integer(), nullable=False),
        sa.Column("setup", sa.JSON(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("rules_version", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=True),
        sa.Column("status_reason", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.user_id"],
            name=op.f("fk_combats_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("combat_id", name=op.f("pk_combats")),
    )
    op.create_index(op.f("ix_combats_owner_user_id"), "combats", ["owner_user_id"])
    op.create_index(op.f("ix_combats_status"), "combats", ["status"])
    op.create_table(
        "combat_actions",
        sa.Column("combat_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("action", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["combat_id"],
            ["combats.combat_id"],
            name=op.f("fk_combat_actions_combat_id_combats"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("combat_id", "seq", name=op.f("pk_combat_actions")),
    )
    _set_rls(True)


def downgrade() -> None:
    _set_rls(False)
    op.drop_table("combat_actions")
    op.drop_index(op.f("ix_combats_status"), table_name="combats")
    op.drop_index(op.f("ix_combats_owner_user_id"), table_name="combats")
    op.drop_table("combats")
