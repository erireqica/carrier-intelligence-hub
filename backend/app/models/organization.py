from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import GmailConnectionStatus, UserRole


class Agency(TimestampMixin, Base):
    __tablename__ = "agencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list[User]] = relationship(back_populates="agency")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('AGENT', 'MANAGER')", name="ck_users_role"),
        Index("ix_users_agency_role", "agency_id", "role"),
        Index("ix_users_agency_active", "agency_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=16), nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agency: Mapped[Agency] = relationship(back_populates="users")
    sessions: Mapped[list[AuthSession]] = relationship(back_populates="user")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_expiration", "user_id", "expires_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class GmailConnection(TimestampMixin, Base):
    __tablename__ = "gmail_connections"
    __table_args__ = (
        CheckConstraint(
            "status IN ('CONNECTED', 'NEEDS_REAUTH', 'ERROR', 'DISCONNECTED')",
            name="ck_gmail_connections_status",
        ),
        UniqueConstraint("agency_id", "gmail_address", name="uq_gmail_agency_address"),
        Index("ix_gmail_connections_owner_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    gmail_address: Mapped[str] = mapped_column(String(320), nullable=False)
    google_account_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[GmailConnectionStatus] = mapped_column(
        Enum(GmailConnectionStatus, native_enum=False, length=24),
        nullable=False,
    )
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempted_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_summary: Mapped[str | None] = mapped_column(String(500))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped[User] = relationship()
