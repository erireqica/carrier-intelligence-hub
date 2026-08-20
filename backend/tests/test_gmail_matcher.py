from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.gmail.matcher import match_carrier
from app.models.carriers import Carrier, CarrierDomain, CarrierSender
from app.models.organization import Agency


def test_whitelist_exact_domain_subdomain_and_suffix_safety(seeded_db: Session) -> None:
    agency = seeded_db.scalar(select(Agency))
    assert agency is not None
    assert match_carrier(seeded_db, agency.id, "alerts@americo.com").name == "Americo"
    assert match_carrier(seeded_db, agency.id, "alerts@mail.americo.com").name == "Americo"
    assert match_carrier(seeded_db, agency.id, "alerts@evilamerico.com") is None


def test_exact_sender_normalization_and_disabled_rules(seeded_db: Session) -> None:
    agency = seeded_db.scalar(select(Agency))
    carrier = seeded_db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    assert agency is not None and carrier is not None
    exact = CarrierSender(
        agency_id=agency.id,
        carrier_id=carrier.id,
        email="development@example.test",
        is_enabled=True,
    )
    seeded_db.add(exact)
    seeded_db.flush()
    assert match_carrier(seeded_db, agency.id, "Development@Example.Test") == carrier

    exact.is_enabled = False
    domain = seeded_db.scalar(select(CarrierDomain).where(CarrierDomain.carrier_id == carrier.id))
    assert domain is not None
    domain.is_enabled = False
    seeded_db.flush()
    assert match_carrier(seeded_db, agency.id, "development@example.test") is None
    assert match_carrier(seeded_db, agency.id, "alerts@americo.com") is None

    domain.is_enabled = True
    carrier.is_enabled = False
    seeded_db.flush()
    assert match_carrier(seeded_db, agency.id, "alerts@americo.com") is None
