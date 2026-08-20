from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.carriers import Carrier
from app.models.enums import (
    AttachmentStatus,
    MessageClassification,
    PolicyStatus,
    Priority,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
)
from app.models.organization import User


class PolicyCase(TimestampMixin, Base):
    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint(
            "current_policy_status IN ('ISSUED', 'PENDING', 'LAPSED', 'DECLINED', "
            "'ACTIVE', 'GRACE_PERIOD', 'UNKNOWN')",
            name="ck_cases_policy_status",
        ),
        CheckConstraint(
            "priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')",
            name="ck_cases_priority",
        ),
        Index(
            "uq_cases_policy_identity",
            "agency_id",
            "carrier_id",
            "policy_number",
            unique=True,
            postgresql_where=text("policy_number IS NOT NULL"),
        ),
        Index("ix_cases_agency_priority_status", "agency_id", "priority", "current_policy_status"),
        Index("ix_cases_assigned_agent", "assigned_agent_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    carrier_id: Mapped[int] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    assigned_agent_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    policy_number: Mapped[str | None] = mapped_column(String(100))
    current_policy_status: Mapped[PolicyStatus] = mapped_column(
        Enum(PolicyStatus, native_enum=False, length=24), nullable=False
    )
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority, native_enum=False, length=16), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    premium_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    effective_date: Mapped[date | None] = mapped_column(Date)
    current_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    carrier: Mapped[Carrier] = relationship()
    assigned_agent: Mapped[User | None] = relationship()
    messages: Mapped[list[CarrierMessage]] = relationship(
        back_populates="case", order_by="CarrierMessage.received_at"
    )
    tasks: Mapped[list[Task]] = relationship(back_populates="case")
    reviews: Mapped[list[ReviewItem]] = relationship(back_populates="case")
    evidence: Mapped[list[CaseEvidence]] = relationship(back_populates="case")


class CarrierMessage(TimestampMixin, Base):
    __tablename__ = "carrier_messages"
    __table_args__ = (
        CheckConstraint(
            "classification IN ('POLICY_ISSUED', 'PENDING_REQUIREMENTS', 'LAPSE_NOTICE', "
            "'COMMISSION_UPDATE', 'OTHER')",
            name="ck_carrier_messages_classification",
        ),
        CheckConstraint(
            "priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')",
            name="ck_carrier_messages_priority",
        ),
        CheckConstraint(
            "processing_status IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'NEEDS_REVIEW', "
            "'FAILED', 'IGNORED')",
            name="ck_carrier_messages_processing_status",
        ),
        CheckConstraint(
            "processing_status != 'PROCESSED' OR "
            "(classification IS NOT NULL AND summary IS NOT NULL AND priority IS NOT NULL)",
            name="ck_carrier_messages_processed_semantics",
        ),
        UniqueConstraint(
            "gmail_connection_id", "gmail_message_id", name="uq_gmail_connection_message"
        ),
        Index("ix_carrier_messages_agency_processing", "agency_id", "processing_status"),
        Index(
            "ix_carrier_messages_processing_retry",
            "processing_status",
            "processing_next_retry_at",
        ),
        Index("ix_carrier_messages_case_received", "case_id", "received_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"))
    carrier_id: Mapped[int] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    gmail_connection_id: Mapped[int | None] = mapped_column(ForeignKey("gmail_connections.id"))
    gmail_message_id: Mapped[str | None] = mapped_column(String(255))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(255))
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    classification: Mapped[MessageClassification | None] = mapped_column(
        Enum(MessageClassification, native_enum=False, length=32),
    )
    summary: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[Priority | None] = mapped_column(Enum(Priority, native_enum=False, length=16))
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, native_enum=False, length=24),
        nullable=False,
    )
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    cleaned_content: Mapped[str] = mapped_column(Text, nullable=False)
    original_deadline_text: Mapped[str | None] = mapped_column(String(500))
    processing_attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_processing_error_code: Mapped[str | None] = mapped_column(String(100))
    processing_next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    case: Mapped[PolicyCase | None] = relationship(back_populates="messages")
    carrier: Mapped[Carrier] = relationship()
    attachments: Mapped[list[Attachment]] = relationship(back_populates="carrier_message")
    analysis: Mapped[MessageAnalysis | None] = relationship(
        back_populates="carrier_message", cascade="all, delete-orphan", uselist=False
    )


class Attachment(TimestampMixin, Base):
    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('PENDING', 'EXTRACTED', 'NEEDS_OCR', 'FAILED', 'UNSUPPORTED')",
            name="ck_attachments_processing_status",
        ),
        UniqueConstraint(
            "carrier_message_id", "external_id", name="uq_attachment_message_external_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    carrier_message_id: Mapped[int] = mapped_column(
        ForeignKey("carrier_messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(2048))
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    processing_status: Mapped[AttachmentStatus] = mapped_column(
        Enum(AttachmentStatus, native_enum=False, length=24), nullable=False
    )
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_count: Mapped[int | None]
    extraction_error_code: Mapped[str | None] = mapped_column(String(100))

    carrier_message: Mapped[CarrierMessage] = relationship(back_populates="attachments")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')",
            name="ck_tasks_priority",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'IN_PROGRESS', 'COMPLETED', 'DISMISSED')",
            name="ck_tasks_status",
        ),
        Index("ix_tasks_assignee_status_due", "assigned_agent_id", "status", "due_at"),
        Index("ix_tasks_agency_priority", "agency_id", "priority"),
        Index(
            "uq_tasks_source_action",
            "source_carrier_message_id",
            "source_action_index",
            unique=True,
            postgresql_where=text(
                "source_carrier_message_id IS NOT NULL AND source_action_index IS NOT NULL"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), nullable=False)
    source_carrier_message_id: Mapped[int | None] = mapped_column(ForeignKey("carrier_messages.id"))
    source_action_index: Mapped[int | None]
    assigned_agent_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority, native_enum=False, length=16), nullable=False
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, length=24), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    case: Mapped[PolicyCase] = relationship(back_populates="tasks")
    assigned_agent: Mapped[User] = relationship()
    source_message: Mapped[CarrierMessage | None] = relationship()


class ReviewItem(TimestampMixin, Base):
    __tablename__ = "review_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'IN_REVIEW', 'RESOLVED', 'DISMISSED')",
            name="ck_review_items_status",
        ),
        Index("ix_reviews_agency_status", "agency_id", "status"),
        Index("ix_reviews_reviewer_status", "assigned_reviewer_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"))
    carrier_message_id: Mapped[int] = mapped_column(
        ForeignKey("carrier_messages.id"), nullable=False
    )
    assigned_reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, native_enum=False, length=24), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    case: Mapped[PolicyCase | None] = relationship(back_populates="reviews")
    carrier_message: Mapped[CarrierMessage] = relationship()
    assigned_reviewer: Mapped[User | None] = relationship()


class CaseEvidence(Base):
    __tablename__ = "case_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    carrier_message_id: Mapped[int] = mapped_column(
        ForeignKey("carrier_messages.id"), nullable=False
    )
    attachment_id: Mapped[int | None] = mapped_column(ForeignKey("attachments.id"))
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    case: Mapped[PolicyCase] = relationship(back_populates="evidence")
    carrier_message: Mapped[CarrierMessage] = relationship()
    attachment: Mapped[Attachment | None] = relationship()


class MessageAnalysis(TimestampMixin, Base):
    __tablename__ = "message_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    carrier_message_id: Mapped[int] = mapped_column(
        ForeignKey("carrier_messages.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    overall_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    model_result_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    validation_flags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    final_result_json: Mapped[dict | None] = mapped_column(JSONB)
    finalized_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    carrier_message: Mapped[CarrierMessage] = relationship(back_populates="analysis")
    finalized_by: Mapped[User | None] = relationship()
