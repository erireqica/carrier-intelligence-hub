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
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
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
    oauth_credential: Mapped[GmailOAuthCredential | None] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
        uselist=False,
    )


class GmailOAuthCredential(TimestampMixin, Base):
    __tablename__ = "gmail_oauth_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    gmail_connection_id: Mapped[int] = mapped_column(
        ForeignKey("gmail_connections.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    encrypted_access_token: Mapped[str | None] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    connection: Mapped[GmailConnection] = relationship(back_populates="oauth_credential")


class GmailOAuthState(Base):
    __tablename__ = "gmail_oauth_states"
    __table_args__ = (
        Index("ix_gmail_oauth_states_expiration", "expires_at"),
        Index("ix_gmail_oauth_states_user_consumed", "user_id", "consumed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    auth_session_id: Mapped[int] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False
    )
    reconnect_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("gmail_connections.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
