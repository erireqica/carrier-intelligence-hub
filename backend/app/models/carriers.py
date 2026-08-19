from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Carrier(TimestampMixin, Base):
    __tablename__ = "carriers"
    __table_args__ = (UniqueConstraint("agency_id", "name", name="uq_carriers_agency_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(40))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    domains: Mapped[list[CarrierDomain]] = relationship(
        back_populates="carrier", cascade="all, delete-orphan"
    )
    senders: Mapped[list[CarrierSender]] = relationship(
        back_populates="carrier", cascade="all, delete-orphan"
    )


class CarrierDomain(TimestampMixin, Base):
    __tablename__ = "carrier_domains"
    __table_args__ = (
        UniqueConstraint("agency_id", "domain", name="uq_carrier_domains_agency_domain"),
        Index("ix_carrier_domains_lookup", "agency_id", "domain", "is_enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    carrier_id: Mapped[int] = mapped_column(ForeignKey("carriers.id", ondelete="CASCADE"))
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    carrier: Mapped[Carrier] = relationship(back_populates="domains")


class CarrierSender(TimestampMixin, Base):
    __tablename__ = "carrier_senders"
    __table_args__ = (
        UniqueConstraint("agency_id", "email", name="uq_carrier_senders_agency_email"),
        Index("ix_carrier_senders_lookup", "agency_id", "email", "is_enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    carrier_id: Mapped[int] = mapped_column(ForeignKey("carriers.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    carrier: Mapped[Carrier] = relationship(back_populates="senders")
