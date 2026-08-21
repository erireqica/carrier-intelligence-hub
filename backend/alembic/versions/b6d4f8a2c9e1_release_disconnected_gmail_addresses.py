"""Release disconnected Gmail addresses while preserving connection history.

Revision ID: b6d4f8a2c9e1
Revises: a9c5f2e7d4b1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6d4f8a2c9e1"
down_revision: str | Sequence[str] | None = "a9c5f2e7d4b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_gmail_agency_address", "gmail_connections", type_="unique")
    op.create_index(
        "uq_gmail_agency_active_address",
        "gmail_connections",
        ["agency_id", "gmail_address"],
        unique=True,
        postgresql_where=sa.text("status != 'DISCONNECTED'"),
    )


def downgrade() -> None:
    op.drop_index("uq_gmail_agency_active_address", table_name="gmail_connections")
    op.create_unique_constraint(
        "uq_gmail_agency_address",
        "gmail_connections",
        ["agency_id", "gmail_address"],
    )
