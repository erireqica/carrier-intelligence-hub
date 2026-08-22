"""add agent removal lifecycle

Revision ID: f6b2c8d4e9a1
Revises: a4f7c2d9e1b6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6b2c8d4e9a1"
down_revision: str | None = "a4f7c2d9e1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("removed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_users_removed_at", "users", ["removed_at"])


def downgrade() -> None:
    op.drop_index("ix_users_removed_at", table_name="users")
    op.drop_column("users", "removed_at")
