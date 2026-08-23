"""Reconcile Review fan-out and stale Review ownership.

Revision ID: a1c4e7b9d2f6
Revises: f8c1d4a7b2e9
"""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from alembic import op
from app.services.mailbox_reconciliation import reconcile_review_consistency

revision: str = "a1c4e7b9d2f6"
down_revision: str | None = "f8c1d4a7b2e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    session = Session(bind=op.get_bind())
    reconcile_review_consistency(session)
    session.flush()


def downgrade() -> None:
    # Redundant synthetic rows cannot be recreated without inventing history.
    pass
