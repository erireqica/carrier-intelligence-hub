"""add structured AI processing

Revision ID: e7b4c2d9f1a3
Revises: c2f4e8a1b6d9
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e7b4c2d9f1a3"
down_revision: str | Sequence[str] | None = "c2f4e8a1b6d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "carrier_messages",
        sa.Column("processing_attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "carrier_messages",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "carrier_messages", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "carrier_messages",
        sa.Column("last_processing_error_code", sa.String(length=100), nullable=True),
    )

    op.drop_constraint("ck_attachments_processing_status", "attachments", type_="check")
    op.create_check_constraint(
        "ck_attachments_processing_status",
        "attachments",
        "processing_status IN ('PENDING', 'EXTRACTED', 'NEEDS_OCR', 'FAILED', 'UNSUPPORTED')",
    )
    op.add_column(
        "attachments", sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("attachments", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column(
        "attachments", sa.Column("extraction_error_code", sa.String(length=100), nullable=True)
    )

    op.add_column("tasks", sa.Column("source_action_index", sa.Integer(), nullable=True))
    op.create_index(
        "uq_tasks_source_action",
        "tasks",
        ["source_carrier_message_id", "source_action_index"],
        unique=True,
        postgresql_where=sa.text(
            "source_carrier_message_id IS NOT NULL AND source_action_index IS NOT NULL"
        ),
    )

    op.create_table(
        "message_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("carrier_message_id", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("overall_confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("model_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("final_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("finalized_by_user_id", sa.Integer(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["carrier_message_id"], ["carrier_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["finalized_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("carrier_message_id"),
    )


def downgrade() -> None:
    op.drop_table("message_analyses")
    op.drop_index("uq_tasks_source_action", table_name="tasks")
    op.drop_column("tasks", "source_action_index")
    op.drop_column("attachments", "extraction_error_code")
    op.drop_column("attachments", "page_count")
    op.drop_column("attachments", "extracted_at")
    op.drop_constraint("ck_attachments_processing_status", "attachments", type_="check")
    op.create_check_constraint(
        "ck_attachments_processing_status",
        "attachments",
        "processing_status IN ('PENDING', 'EXTRACTED', 'FAILED', 'UNSUPPORTED')",
    )
    op.drop_column("carrier_messages", "last_processing_error_code")
    op.drop_column("carrier_messages", "processed_at")
    op.drop_column("carrier_messages", "processing_started_at")
    op.drop_column("carrier_messages", "processing_attempt_count")
