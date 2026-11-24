"""auth: users.username_normalized/role/created_at, refresh_tokens; RLS on Postgres

Revision ID: b3d9e6a41c27
Revises: 8c4d1e2f7a61
Create Date: 2026-11-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d9e6a41c27"
down_revision: Union[str, Sequence[str], None] = "8c4d1e2f7a61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every game table. Supabase exposes `public` tables through its REST API to the anon
# key; RLS with no policies blocks that, while the server (role `postgres`) is
# unaffected (docs/architecture.md "Security checklist").
RLS_TABLES = ("users", "worlds", "worldgen_pins", "body_names", "refresh_tokens")


def _set_rls(enabled: bool) -> None:
    # The one sanctioned dialect-specific statement (rule 10 exception, documented in
    # docs/architecture.md): RLS has no SQLite equivalent and isn't needed there.
    if op.get_bind().dialect.name != "postgresql":
        return
    verb = "ENABLE" if enabled else "DISABLE"
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} {verb} ROW LEVEL SECURITY")


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("username_normalized", sa.String(32), nullable=True))
        batch.add_column(
            sa.Column("role", sa.String(16), server_default="player", nullable=False)
        )
        batch.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
    op.execute(sa.text("UPDATE users SET username_normalized = lower(username)"))
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "username_normalized", existing_type=sa.String(32), nullable=False
        )
        batch.create_unique_constraint(
            op.f("uq_users_username_normalized"), ["username_normalized"]
        )

    op.create_table(
        "refresh_tokens",
        sa.Column(
            "token_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"),
        "refresh_tokens",
        ["family_id"],
        unique=False,
    )
    _set_rls(True)


def downgrade() -> None:
    _set_rls(False)
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint(op.f("uq_users_username_normalized"), type_="unique")
        batch.drop_column("created_at")
        batch.drop_column("role")
        batch.drop_column("username_normalized")
