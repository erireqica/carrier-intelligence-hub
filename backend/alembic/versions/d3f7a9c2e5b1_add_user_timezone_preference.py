"""Add an optional display timezone to users.

Revision ID: d3f7a9c2e5b1
Revises: c4e7a1d9b5f2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3f7a9c2e5b1"
down_revision: str | None = "c4e7a1d9b5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "timezone")
