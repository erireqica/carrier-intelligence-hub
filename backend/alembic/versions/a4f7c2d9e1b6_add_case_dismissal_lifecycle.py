"""add case dismissal lifecycle

Revision ID: a4f7c2d9e1b6
Revises: d1e6a9b4c2f7
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4f7c2d9e1b6"
down_revision: str | None = "d1e6a9b4c2f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("dismissed_at", sa.DateTime(timezone=True)))
    op.add_column("cases", sa.Column("dismissed_by_user_id", sa.Integer()))
    op.create_foreign_key(
        "fk_cases_dismissed_by_user_id_users",
        "cases",
        "users",
        ["dismissed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_cases_agency_dismissed", "cases", ["agency_id", "dismissed_at"])


def downgrade() -> None:
    op.drop_index("ix_cases_agency_dismissed", table_name="cases")
    op.drop_constraint("fk_cases_dismissed_by_user_id_users", "cases", type_="foreignkey")
    op.drop_column("cases", "dismissed_by_user_id")
    op.drop_column("cases", "dismissed_at")
