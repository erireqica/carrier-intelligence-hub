"""add pipeline reliability and Gmail label reconciliation

Revision ID: a9c5f2e7d4b1
Revises: f3a8d1c6b4e2
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a9c5f2e7d4b1"
down_revision: str | Sequence[str] | None = "f3a8d1c6b4e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "carrier_messages",
        sa.Column("processing_next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_carrier_messages_processing_retry",
        "carrier_messages",
        ["processing_status", "processing_next_retry_at"],
    )

    op.create_table(
        "gmail_managed_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("gmail_connection_id", sa.Integer(), nullable=False),
        sa.Column("label_key", sa.String(length=32), nullable=False),
        sa.Column("label_name", sa.String(length=100), nullable=False),
        sa.Column("gmail_label_id", sa.String(length=255), nullable=False),
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
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.ForeignKeyConstraint(
            ["gmail_connection_id"], ["gmail_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gmail_connection_id", "gmail_label_id", name="uq_gmail_managed_label_id"
        ),
        sa.UniqueConstraint("gmail_connection_id", "label_key", name="uq_gmail_managed_label_key"),
    )

    op.create_table(
        "gmail_thread_label_syncs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("gmail_connection_id", sa.Integer(), nullable=False),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("claimed_generation", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "applied_label_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'RETRY_WAIT', 'APPLIED', "
            "'NEEDS_PERMISSION', 'FAILED')",
            name="ck_gmail_thread_label_sync_status",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.ForeignKeyConstraint(
            ["gmail_connection_id"], ["gmail_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gmail_connection_id", "gmail_thread_id", name="uq_gmail_thread_label_sync"
        ),
    )
    op.create_index(
        "ix_gmail_label_sync_due",
        "gmail_thread_label_syncs",
        ["status", "next_retry_at"],
    )
    op.create_index(
        "ix_gmail_label_sync_connection_thread",
        "gmail_thread_label_syncs",
        ["gmail_connection_id", "gmail_thread_id"],
    )
    op.execute(
        """
        INSERT INTO gmail_thread_label_syncs
            (agency_id, gmail_connection_id, gmail_thread_id, status, generation,
             attempt_count, applied_label_keys, created_at, updated_at)
        SELECT DISTINCT agency_id, gmail_connection_id, gmail_thread_id,
               'PENDING', 1, 0, '[]'::jsonb, now(), now()
        FROM carrier_messages
        WHERE gmail_connection_id IS NOT NULL
          AND gmail_thread_id IS NOT NULL
          AND gmail_thread_id <> ''
        ON CONFLICT (gmail_connection_id, gmail_thread_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_gmail_label_sync_connection_thread", table_name="gmail_thread_label_syncs")
    op.drop_index("ix_gmail_label_sync_due", table_name="gmail_thread_label_syncs")
    op.drop_table("gmail_thread_label_syncs")
    op.drop_table("gmail_managed_labels")
    op.drop_index("ix_carrier_messages_processing_retry", table_name="carrier_messages")
    op.drop_column("carrier_messages", "processing_next_retry_at")
