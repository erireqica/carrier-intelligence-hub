"""expand Gmail attachment identity

Revision ID: f3a8d1c6b4e2
Revises: e7b4c2d9f1a3
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a8d1c6b4e2"
down_revision: str | Sequence[str] | None = "e7b4c2d9f1a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "attachments",
        "external_id",
        existing_type=sa.String(length=255),
        type_=sa.String(length=2048),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "attachments",
        "external_id",
        existing_type=sa.String(length=2048),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
