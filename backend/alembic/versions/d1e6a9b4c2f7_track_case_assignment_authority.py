"""Track authoritative case assignment and retire manager-owned Gmail access.

Revision ID: d1e6a9b4c2f7
Revises: b6d4f8a2c9e1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e6a9b4c2f7"
down_revision: str | Sequence[str] | None = "b6d4f8a2c9e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cases",
        sa.Column(
            "assignment_source",
            sa.String(length=24),
            server_default="GMAIL",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_cases_assignment_source",
        "cases",
        "assignment_source IN ('GMAIL', 'MANAGER', 'GMAIL_HANDOFF')",
    )

    # Reassign only when existing message lineage identifies an active Agent.
    op.execute(
        sa.text(
            """
            WITH candidates AS (
                SELECT c.id AS case_id,
                       (
                           SELECT gc.user_id
                           FROM carrier_messages cm
                           JOIN gmail_connections gc ON gc.id = cm.gmail_connection_id
                           JOIN users candidate ON candidate.id = gc.user_id
                           WHERE cm.case_id = c.id
                             AND candidate.agency_id = c.agency_id
                             AND candidate.role = 'AGENT'
                             AND candidate.is_active IS TRUE
                           ORDER BY cm.received_at DESC, cm.id DESC
                           LIMIT 1
                       ) AS agent_id
                FROM cases c
                JOIN users owner ON owner.id = c.assigned_agent_id
                WHERE owner.role = 'MANAGER'
            )
            UPDATE cases c
            SET assigned_agent_id = candidates.agent_id,
                assignment_source = 'GMAIL'
            FROM candidates
            WHERE c.id = candidates.case_id
              AND candidates.agent_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE tasks t
            SET assigned_agent_id = c.assigned_agent_id
            FROM cases c, users prior_owner, users case_owner
            WHERE t.case_id = c.id
              AND prior_owner.id = t.assigned_agent_id
              AND prior_owner.role = 'MANAGER'
              AND case_owner.id = c.assigned_agent_id
              AND case_owner.role = 'AGENT'
              AND t.status IN ('OPEN', 'IN_PROGRESS')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE review_items r
            SET assigned_reviewer_id = c.assigned_agent_id
            FROM cases c, users prior_owner, users case_owner
            WHERE r.case_id = c.id
              AND prior_owner.id = r.assigned_reviewer_id
              AND prior_owner.role = 'MANAGER'
              AND case_owner.id = c.assigned_agent_id
              AND case_owner.role = 'AGENT'
              AND r.status IN ('OPEN', 'IN_REVIEW')
            """
        )
    )

    # An unresolved manager review without a safely identified Agent becomes unassigned,
    # rather than being distributed arbitrarily or finalized incorrectly.
    op.execute(
        sa.text(
            """
            UPDATE review_items r
            SET assigned_reviewer_id = NULL
            FROM users owner
            WHERE owner.id = r.assigned_reviewer_id
              AND owner.role = 'MANAGER'
              AND r.status IN ('OPEN', 'IN_REVIEW')
            """
        )
    )

    # Managers can no longer own inboxes. Preserve the connection history while
    # preventing any further access or processing through old manager credentials.
    op.execute(
        sa.text(
            """
            DELETE FROM gmail_oauth_credentials credential
            USING gmail_connections connection, users owner
            WHERE credential.gmail_connection_id = connection.id
              AND owner.id = connection.user_id
              AND owner.role = 'MANAGER'
              AND connection.status != 'DISCONNECTED'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE gmail_connections connection
            SET status = 'DISCONNECTED',
                last_error_summary = NULL
            FROM users owner
            WHERE owner.id = connection.user_id
              AND owner.role = 'MANAGER'
              AND connection.status != 'DISCONNECTED'
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint("ck_cases_assignment_source", "cases", type_="check")
    op.drop_column("cases", "assignment_source")
