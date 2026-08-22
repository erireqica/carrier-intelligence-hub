"""Add normalized user profile photos.

Revision ID: e2c7a9f4b1d6
Revises: d8a2f4c6e1b9
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2c7a9f4b1d6"
down_revision: str | None = "d8a2f4c6e1b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_image", sa.LargeBinary(), nullable=True))
    op.add_column("users", sa.Column("avatar_content_type", sa.String(length=32), nullable=True))
    op.add_column(
        "users",
        sa.Column("avatar_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_updated_at")
    op.drop_column("users", "avatar_content_type")
    op.drop_column("users", "avatar_image")
