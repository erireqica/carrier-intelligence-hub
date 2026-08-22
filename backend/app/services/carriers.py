from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.schemas.domain import (
    CarrierDomainItem,
    CarrierItem,
    CarrierSenderItem,
    CarrierWrite,
    DomainWrite,
    SenderWrite,
)
from app.models.carriers import Carrier, CarrierDomain, CarrierSender
from app.models.operations import CarrierMessage, PolicyCase
from app.services.audit import record_audit_event
from app.services.auth import AuthContext


def carrier_item(carrier: Carrier) -> CarrierItem:
    return CarrierItem(
        id=carrier.id,
        name=carrier.name,
        code=carrier.code,
        notes=carrier.notes,
        is_enabled=carrier.is_enabled,
        domains=[
            CarrierDomainItem(id=item.id, domain=item.domain, is_enabled=item.is_enabled)
            for item in sorted(carrier.domains, key=lambda value: value.domain)
        ],
        senders=[
            CarrierSenderItem(id=item.id, email=item.email, is_enabled=item.is_enabled)
            for item in sorted(carrier.senders, key=lambda value: value.email)
        ],
    )


def _carrier_query(agency_id: int):
    return (
        select(Carrier)
        .where(Carrier.agency_id == agency_id)
        .options(selectinload(Carrier.domains), selectinload(Carrier.senders))
        .execution_options(populate_existing=True)
    )


def list_carriers(db: Session, current: AuthContext) -> list[CarrierItem]:
    carriers = db.scalars(_carrier_query(current.user.agency_id).order_by(Carrier.name)).all()
    return [carrier_item(carrier) for carrier in carriers]


def get_carrier(db: Session, current: AuthContext, carrier_id: int) -> Carrier:
    carrier = db.scalar(_carrier_query(current.user.agency_id).where(Carrier.id == carrier_id))
    if carrier is None:
        raise HTTPException(status_code=404, detail="Carrier not found")
    return carrier


def create_carrier(db: Session, current: AuthContext, data: CarrierWrite) -> CarrierItem:
    carrier = Carrier(agency_id=current.user.agency_id, **data.model_dump())
    db.add(carrier)
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="CARRIER_CREATED",
        description=f"Carrier created: {carrier.name}",
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A carrier with this name already exists"
        ) from error
    return carrier_item(get_carrier(db, current, carrier.id))


def update_carrier(
    db: Session, current: AuthContext, carrier_id: int, data: CarrierWrite
) -> CarrierItem:
    carrier = get_carrier(db, current, carrier_id)
    for field, value in data.model_dump().items():
        setattr(carrier, field, value)
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="CARRIER_UPDATED",
        description=f"Carrier updated: {carrier.name}",
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A carrier with this name already exists"
        ) from error
    return carrier_item(get_carrier(db, current, carrier.id))


def delete_carrier(db: Session, current: AuthContext, carrier_id: int) -> None:
    carrier = get_carrier(db, current, carrier_id)
    case_count = (
        db.scalar(
            select(func.count()).select_from(PolicyCase).where(PolicyCase.carrier_id == carrier.id)
        )
        or 0
    )
    message_count = (
        db.scalar(
            select(func.count())
            .select_from(CarrierMessage)
            .where(CarrierMessage.carrier_id == carrier.id)
        )
        or 0
    )
    if case_count or message_count:
        raise HTTPException(
            status_code=409,
            detail=(
                "This carrier has existing policy/message history and cannot be deleted. "
                "Disable it instead."
            ),
        )
    carrier_name = carrier.name
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="CARRIER_DELETED",
        description=f"Carrier deleted: {carrier_name}",
        metadata={"carrier_id": carrier.id, "carrier_name": carrier_name},
    )
    db.delete(carrier)
    db.commit()


def add_domain(
    db: Session, current: AuthContext, carrier_id: int, data: DomainWrite
) -> CarrierItem:
    carrier = get_carrier(db, current, carrier_id)
    db.add(
        CarrierDomain(
            agency_id=current.user.agency_id,
            carrier_id=carrier.id,
            domain=data.domain,
            is_enabled=data.is_enabled,
        )
    )
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="WHITELIST_UPDATED",
        description=f"Approved domain added for {carrier.name}",
        metadata={"domain": data.domain},
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This domain is already configured") from error
    return carrier_item(get_carrier(db, current, carrier.id))


def add_sender(
    db: Session, current: AuthContext, carrier_id: int, data: SenderWrite
) -> CarrierItem:
    carrier = get_carrier(db, current, carrier_id)
    email = str(data.email)
    db.add(
        CarrierSender(
            agency_id=current.user.agency_id,
            carrier_id=carrier.id,
            email=email,
            is_enabled=data.is_enabled,
        )
    )
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="WHITELIST_UPDATED",
        description=f"Approved sender added for {carrier.name}",
        metadata={"email": email},
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This sender is already configured") from error
    return carrier_item(get_carrier(db, current, carrier.id))


def set_whitelist_enabled(
    db: Session,
    current: AuthContext,
    *,
    carrier_id: int,
    item_id: int,
    item_type: str,
    is_enabled: bool,
) -> CarrierItem:
    carrier = get_carrier(db, current, carrier_id)
    model = CarrierDomain if item_type == "domain" else CarrierSender
    item = db.scalar(
        select(model).where(
            model.id == item_id,
            model.carrier_id == carrier.id,
            model.agency_id == current.user.agency_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Whitelist entry not found")
    item.is_enabled = is_enabled
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="WHITELIST_UPDATED",
        description=(
            f"{item_type.title()} {'enabled' if is_enabled else 'disabled'} for {carrier.name}"
        ),
    )
    db.commit()
    return carrier_item(get_carrier(db, current, carrier.id))


def remove_whitelist_entry(
    db: Session,
    current: AuthContext,
    *,
    carrier_id: int,
    item_id: int,
    item_type: str,
) -> CarrierItem:
    carrier = get_carrier(db, current, carrier_id)
    model = CarrierDomain if item_type == "domain" else CarrierSender
    item = db.scalar(
        select(model).where(
            model.id == item_id,
            model.carrier_id == carrier.id,
            model.agency_id == current.user.agency_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Whitelist entry not found")
    db.delete(item)
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="WHITELIST_UPDATED",
        description=f"{item_type.title()} removed from {carrier.name}",
    )
    db.commit()
    return carrier_item(get_carrier(db, current, carrier.id))
