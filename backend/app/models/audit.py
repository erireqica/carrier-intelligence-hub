from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AuditSeverity
from app.models.organization import User


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR')", name="ck_audit_events_severity"
        ),
        Index("ix_audit_events_agency_created", "agency_id", "created_at"),
        Index("ix_audit_events_agency_type", "agency_id", "event_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"))
    carrier_message_id: Mapped[int | None] = mapped_column(ForeignKey("carrier_messages.id"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[AuditSeverity] = mapped_column(
        Enum(AuditSeverity, native_enum=False, length=16), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    actor: Mapped[User | None] = relationship()
