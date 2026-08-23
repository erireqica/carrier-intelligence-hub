"""Add the durable Gmail observed-message ledger.

Revision ID: c4e7a1d9b5f2
Revises: b2d5f8a1c3e7
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e7a1d9b5f2"
down_revision: str | None = "b2d5f8a1c3e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gmail_observed_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gmail_connection_id", sa.Integer(), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["gmail_connection_id"],
            ["gmail_connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gmail_connection_id",
            "gmail_message_id",
            name="uq_gmail_observed_connection_message",
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO gmail_observed_messages
                (gmail_connection_id, gmail_message_id, gmail_thread_id, first_seen_at)
            SELECT DISTINCT ON (gmail_connection_id, gmail_message_id)
                gmail_connection_id,
                gmail_message_id,
                gmail_thread_id,
                created_at
            FROM carrier_messages
            WHERE gmail_connection_id IS NOT NULL
              AND gmail_message_id IS NOT NULL
            ORDER BY gmail_connection_id, gmail_message_id, created_at, id
            ON CONFLICT (gmail_connection_id, gmail_message_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("gmail_observed_messages")
