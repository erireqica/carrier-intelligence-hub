from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import normalize_email
from app.models.carriers import Carrier, CarrierDomain, CarrierSender


def match_carrier(db: Session, agency_id: int, sender: str) -> Carrier | None:
    normalized = normalize_email(sender)
    exact = db.scalar(
        select(Carrier)
        .join(CarrierSender, CarrierSender.carrier_id == Carrier.id)
        .where(
            Carrier.agency_id == agency_id,
            CarrierSender.agency_id == agency_id,
            Carrier.is_enabled.is_(True),
            CarrierSender.is_enabled.is_(True),
            CarrierSender.email == normalized,
        )
    )
    if exact is not None:
        return exact
    if "@" not in normalized:
        return None
    sender_domain = normalized.rsplit("@", 1)[1]
    rows = db.execute(
        select(Carrier, CarrierDomain.domain)
        .join(CarrierDomain, CarrierDomain.carrier_id == Carrier.id)
        .where(
            Carrier.agency_id == agency_id,
            CarrierDomain.agency_id == agency_id,
            Carrier.is_enabled.is_(True),
            CarrierDomain.is_enabled.is_(True),
        )
    ).all()
    for carrier, approved_domain in rows:
        if sender_domain == approved_domain or sender_domain.endswith(f".{approved_domain}"):
            return carrier
    return None
