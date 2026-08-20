"""add Gmail OAuth credential and state storage

Revision ID: c2f4e8a1b6d9
Revises: a4c9e3f7b2d1
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c2f4e8a1b6d9"
down_revision: str | Sequence[str] | None = "a4c9e3f7b2d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gmail_oauth_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gmail_connection_id", sa.Integer(), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "granted_scopes",
            postgresql.JSONB(astext_type=sa.Text()),
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
        sa.ForeignKeyConstraint(
            ["gmail_connection_id"], ["gmail_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gmail_connection_id"),
    )
    op.create_table(
        "gmail_oauth_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("auth_session_id", sa.Integer(), nullable=False),
        sa.Column("reconnect_connection_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["auth_session_id"], ["auth_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reconnect_connection_id"], ["gmail_connections.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index(
        "ix_gmail_oauth_states_expiration", "gmail_oauth_states", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_gmail_oauth_states_user_consumed",
        "gmail_oauth_states",
        ["user_id", "consumed_at"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_attachment_message_external_id",
        "attachments",
        ["carrier_message_id", "external_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_attachment_message_external_id", "attachments", type_="unique")
    op.drop_index("ix_gmail_oauth_states_user_consumed", table_name="gmail_oauth_states")
    op.drop_index("ix_gmail_oauth_states_expiration", table_name="gmail_oauth_states")
    op.drop_table("gmail_oauth_states")
    op.drop_table("gmail_oauth_credentials")
