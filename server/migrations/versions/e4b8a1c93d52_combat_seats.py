"""combat_seats + combats.activation_timer_s (online 1v1 battles); RLS on Postgres

Revision ID: e4b8a1c93d52
Revises: c7a2f0d58e14
Create Date: 2026-11-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b8a1c93d52"
down_revision: Union[str, Sequence[str], None] = "c7a2f0d58e14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _set_rls(enabled: bool) -> None:
    # Postgres-only (the documented rule-10 exception, see b3d9e6a41c27_auth_and_rls).
    if op.get_bind().dialect.name != "postgresql":
        return
    verb = "ENABLE" if enabled else "DISABLE"
    op.execute(f"ALTER TABLE combat_seats {verb} ROW LEVEL SECURITY")


def upgrade() -> None:
    with op.batch_alter_table("combats") as batch:
        batch.add_column(sa.Column("activation_timer_s", sa.Integer(), nullable=True))
    op.create_table(
        "combat_seats",
        sa.Column("combat_id", sa.Uuid(), nullable=False),
        sa.Column("side", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["combat_id"],
            ["combats.combat_id"],
            name=op.f("fk_combat_seats_combat_id_combats"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name=op.f("fk_combat_seats_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("combat_id", "side", name=op.f("pk_combat_seats")),
    )
    op.create_index(op.f("ix_combat_seats_user_id"), "combat_seats", ["user_id"])
    _set_rls(True)


def downgrade() -> None:
    _set_rls(False)
    op.drop_index(op.f("ix_combat_seats_user_id"), table_name="combat_seats")
    op.drop_table("combat_seats")
    with op.batch_alter_table("combats") as batch:
        batch.drop_column("activation_timer_s")
