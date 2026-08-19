"""harden carrier message lifecycle

Revision ID: a4c9e3f7b2d1
Revises: e80f1b0bf63e
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4c9e3f7b2d1"
down_revision: str | Sequence[str] | None = "e80f1b0bf63e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow source messages to exist before semantic analysis completes."""
    op.alter_column(
        "carrier_messages",
        "classification",
        existing_type=sa.String(length=32),
        nullable=True,
    )
    op.alter_column(
        "carrier_messages",
        "summary",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.alter_column(
        "carrier_messages",
        "priority",
        existing_type=sa.String(length=16),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_carrier_messages_processed_semantics",
        "carrier_messages",
        "processing_status != 'PROCESSED' OR "
        "(classification IS NOT NULL AND summary IS NOT NULL AND priority IS NOT NULL)",
    )


def downgrade() -> None:
    """Restore the Stage 2 non-null contract when all rows are compatible."""
    op.drop_constraint(
        "ck_carrier_messages_processed_semantics",
        "carrier_messages",
        type_="check",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM carrier_messages
                WHERE classification IS NULL OR summary IS NULL OR priority IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade while carrier messages have incomplete semantic fields';
            END IF;
        END
        $$;
        """
    )
    op.alter_column(
        "carrier_messages",
        "priority",
        existing_type=sa.String(length=16),
        nullable=False,
    )
    op.alter_column(
        "carrier_messages",
        "summary",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "carrier_messages",
        "classification",
        existing_type=sa.String(length=32),
        nullable=False,
    )
