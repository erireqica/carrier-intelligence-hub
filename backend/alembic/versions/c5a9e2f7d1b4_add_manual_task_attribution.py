"""Add manual Task creator and completion attribution.

Revision ID: c5a9e2f7d1b4
Revises: e2c7a9f4b1d6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5a9e2f7d1b4"
down_revision: str | None = "e2c7a9f4b1d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("created_by_user_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("completed_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_created_by_user_id_users",
        "tasks",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tasks_completed_by_user_id_users",
        "tasks",
        "users",
        ["completed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tasks_completed_by_user_id_users", "tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_created_by_user_id_users", "tasks", type_="foreignkey")
    op.drop_column("tasks", "completed_by_user_id")
    op.drop_column("tasks", "created_by_user_id")
