"""Enforce one Review per physical Gmail message.

Revision ID: b2d5f8a1c3e7
Revises: a1c4e7b9d2f6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from alembic import op
from app.services.mailbox_reconciliation import reconcile_single_review_per_message

revision: str = "b2d5f8a1c3e7"
down_revision: str | None = "a1c4e7b9d2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    session = Session(bind=op.get_bind())
    reconcile_single_review_per_message(session)
    session.flush()
    op.drop_index("uq_reviews_active_message", table_name="review_items")
    op.create_index(
        "uq_reviews_message",
        "review_items",
        ["carrier_message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_reviews_message", table_name="review_items")
    op.create_index(
        "uq_reviews_active_message",
        "review_items",
        ["carrier_message_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('OPEN', 'IN_REVIEW')"),
    )
