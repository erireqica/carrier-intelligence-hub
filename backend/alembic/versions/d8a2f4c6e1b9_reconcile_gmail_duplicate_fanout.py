"""Reconcile legacy Gmail duplicate fan-out and guard active reviews.

Revision ID: d8a2f4c6e1b9
Revises: c7e9a1d4f2b6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from alembic import op
from app.services.mailbox_reconciliation import reconcile_legacy_duplicate_fanout

revision: str = "d8a2f4c6e1b9"
down_revision: str | None = "c7e9a1d4f2b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    session = Session(bind=op.get_bind())
    reconcile_legacy_duplicate_fanout(session)
    session.flush()
    op.create_index(
        "uq_reviews_active_message",
        "review_items",
        ["carrier_message_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('OPEN', 'IN_REVIEW')"),
    )


def downgrade() -> None:
    op.drop_index("uq_reviews_active_message", table_name="review_items")
