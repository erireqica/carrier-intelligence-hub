"""Stabilize logical Gmail mailbox identity and reconcile reconnect duplicates.

Revision ID: c7e9a1d4f2b6
Revises: f6b2c8d4e9a1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from alembic import op
from app.services.mailbox_reconciliation import reconcile_duplicate_gmail_connections

revision: str = "c7e9a1d4f2b6"
down_revision: str | None = "f6b2c8d4e9a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    session = Session(bind=op.get_bind())
    reconcile_duplicate_gmail_connections(session)
    session.flush()
    op.drop_index("uq_gmail_agency_active_address", table_name="gmail_connections")
    op.create_unique_constraint(
        "uq_gmail_agency_address",
        "gmail_connections",
        ["agency_id", "gmail_address"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_gmail_agency_address", "gmail_connections", type_="unique")
    op.create_index(
        "uq_gmail_agency_active_address",
        "gmail_connections",
        ["agency_id", "gmail_address"],
        unique=True,
        postgresql_where=sa.text("status != 'DISCONNECTED'"),
    )
