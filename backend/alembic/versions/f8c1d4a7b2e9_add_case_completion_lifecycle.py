"""Add explicit Case completion lifecycle attribution.

Revision ID: f8c1d4a7b2e9
Revises: c5a9e2f7d1b4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8c1d4a7b2e9"
down_revision: str | None = "c5a9e2f7d1b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cases", sa.Column("completed_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_cases_completed_by_user_id_users",
        "cases",
        "users",
        ["completed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_cases_agency_completed",
        "cases",
        ["agency_id", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_cases_agency_completed", table_name="cases")
    op.drop_constraint("fk_cases_completed_by_user_id_users", "cases", type_="foreignkey")
    op.drop_column("cases", "completed_by_user_id")
    op.drop_column("cases", "completed_at")
