from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import GmailLabelKey, GmailLabelSyncStatus
from app.models.organization import GmailConnection


class GmailManagedLabel(TimestampMixin, Base):
    __tablename__ = "gmail_managed_labels"
    __table_args__ = (
        UniqueConstraint("gmail_connection_id", "label_key", name="uq_gmail_managed_label_key"),
        UniqueConstraint("gmail_connection_id", "gmail_label_id", name="uq_gmail_managed_label_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    gmail_connection_id: Mapped[int] = mapped_column(
        ForeignKey("gmail_connections.id", ondelete="CASCADE"), nullable=False
    )
    label_key: Mapped[GmailLabelKey] = mapped_column(
        Enum(GmailLabelKey, native_enum=False, length=32), nullable=False
    )
    label_name: Mapped[str] = mapped_column(String(100), nullable=False)
    gmail_label_id: Mapped[str] = mapped_column(String(255), nullable=False)

    connection: Mapped[GmailConnection] = relationship()


class GmailThreadLabelSync(TimestampMixin, Base):
    __tablename__ = "gmail_thread_label_syncs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'RETRY_WAIT', 'APPLIED', "
            "'NEEDS_PERMISSION', 'FAILED')",
            name="ck_gmail_thread_label_sync_status",
        ),
        UniqueConstraint(
            "gmail_connection_id", "gmail_thread_id", name="uq_gmail_thread_label_sync"
        ),
        Index("ix_gmail_label_sync_due", "status", "next_retry_at"),
        Index(
            "ix_gmail_label_sync_connection_thread",
            "gmail_connection_id",
            "gmail_thread_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    gmail_connection_id: Mapped[int] = mapped_column(
        ForeignKey("gmail_connections.id", ondelete="CASCADE"), nullable=False
    )
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[GmailLabelSyncStatus] = mapped_column(
        Enum(GmailLabelSyncStatus, native_enum=False, length=24), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    claimed_generation: Mapped[int | None] = mapped_column(Integer)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    applied_label_keys: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    connection: Mapped[GmailConnection] = relationship()
