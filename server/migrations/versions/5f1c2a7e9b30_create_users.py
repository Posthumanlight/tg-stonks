"""create users

Revision ID: 5f1c2a7e9b30
Revises:
Create Date: 2026-11-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5f1c2a7e9b30"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "user_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )


def downgrade() -> None:
    op.drop_table("users")
