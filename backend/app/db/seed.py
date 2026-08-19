from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models.audit import AuditEvent
from app.models.carriers import Carrier, CarrierDomain
from app.models.enums import (
    AttachmentStatus,
    AuditSeverity,
    MessageClassification,
    PolicyStatus,
    Priority,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
    UserRole,
)
from app.models.operations import (
    Attachment,
    CarrierMessage,
    CaseEvidence,
    PolicyCase,
    ReviewItem,
    Task,
)
from app.models.organization import Agency, User

from .session import SessionLocal

AGENCY_NAME = "Harbor Point Insurance Agency"


def get_or_create(db: Session, model, defaults: dict | None = None, **identity):
    instance = db.scalar(select(model).filter_by(**identity))
    if instance is None:
        instance = model(**identity, **(defaults or {}))
        db.add(instance)
        db.flush()
    return instance


def seed_users(db: Session, agency: Agency, password: str) -> dict[str, User]:
    definitions = {
        "manager@demo.local": ("Morgan Reed", UserRole.MANAGER),
        "agent.one@demo.local": ("Elena Torres", UserRole.AGENT),
        "agent.two@demo.local": ("Marcus Lee", UserRole.AGENT),
    }
    users: dict[str, User] = {}
    for email, (name, role) in definitions.items():
        user = get_or_create(
            db,
            User,
            agency_id=agency.id,
            email=email,
            defaults={
                "full_name": name,
                "role": role,
                "password_hash": hash_password(password),
                "is_active": True,
            },
        )
        user.full_name = name
        user.role = role
        user.is_active = True
        if not verify_password(password, user.password_hash):
            user.password_hash = hash_password(password)
        users[email] = user
    return users


def seed_carriers(db: Session, agency: Agency) -> dict[str, Carrier]:
    definitions = {
        "Americo": ("AMERICO", "Life insurance carrier", "americo.com"),
        "Aetna": ("AETNA", "Health and supplemental insurance carrier", "aetna.com"),
        "American Amicable / AMAM": (
            "AMAM",
            "American Amicable group carrier",
            "americanamicable.com",
        ),
    }
    carriers: dict[str, Carrier] = {}
    for name, (code, notes, domain) in definitions.items():
        carrier = get_or_create(
            db,
            Carrier,
            agency_id=agency.id,
            name=name,
            defaults={"code": code, "notes": notes, "is_enabled": True},
        )
        carrier.code = code
        carrier.notes = notes
        carrier.is_enabled = True
        approved_domain = get_or_create(
            db,
            CarrierDomain,
            agency_id=agency.id,
            domain=domain,
            defaults={"carrier_id": carrier.id, "is_enabled": True},
        )
        approved_domain.carrier_id = carrier.id
        approved_domain.is_enabled = True
        carriers[name] = carrier
    return carriers


def seed_case(
    db: Session,
    *,
    agency: Agency,
    carrier: Carrier,
    agent: User,
    client_name: str,
    policy_number: str,
    policy_status: PolicyStatus,
    priority: Priority,
    summary: str,
    premium: Decimal | None = None,
    effective_date: date | None = None,
    deadline: datetime | None = None,
) -> PolicyCase:
    case = get_or_create(
        db,
        PolicyCase,
        agency_id=agency.id,
        carrier_id=carrier.id,
        policy_number=policy_number,
        defaults={
            "assigned_agent_id": agent.id,
            "client_name": client_name,
            "current_policy_status": policy_status,
            "priority": priority,
            "summary": summary,
        },
    )
    case.assigned_agent_id = agent.id
    case.client_name = client_name
    case.current_policy_status = policy_status
    case.priority = priority
    case.summary = summary
    case.premium_amount = premium
    case.currency = "USD" if premium is not None else None
    case.effective_date = effective_date
    case.current_deadline = deadline
    return case


def seed_message(
    db: Session,
    *,
    agency: Agency,
    case: PolicyCase,
    carrier: Carrier,
    fixture_id: str,
    sender: str,
    subject: str,
    received_at: datetime,
    classification: MessageClassification,
    summary: str,
    priority: Priority,
    body: str,
    status: ProcessingStatus = ProcessingStatus.PROCESSED,
    deadline_text: str | None = None,
) -> CarrierMessage:
    message = get_or_create(
        db,
        CarrierMessage,
        agency_id=agency.id,
        gmail_message_id=fixture_id,
        defaults={
            "case_id": case.id,
            "carrier_id": carrier.id,
            "sender": sender,
            "subject": subject,
            "received_at": received_at,
            "classification": classification,
            "summary": summary,
            "priority": priority,
            "processing_status": status,
            "raw_content": body,
            "cleaned_content": body,
            "original_deadline_text": deadline_text,
        },
    )
    return message


def seed_task(
    db: Session,
    *,
    agency: Agency,
    case: PolicyCase,
    message: CarrierMessage,
    agent: User,
    title: str,
    description: str,
    priority: Priority,
    due_at: datetime | None,
    status: TaskStatus = TaskStatus.OPEN,
) -> Task:
    task = get_or_create(
        db,
        Task,
        case_id=case.id,
        title=title,
        defaults={
            "agency_id": agency.id,
            "source_carrier_message_id": message.id,
            "assigned_agent_id": agent.id,
            "description": description,
            "priority": priority,
            "due_at": due_at,
            "status": status,
            "completed_at": datetime(2026, 8, 5, 14, 0, tzinfo=UTC)
            if status is TaskStatus.COMPLETED
            else None,
        },
    )
    return task


def seed_demo_data(db: Session, password: str) -> None:
    agency = get_or_create(
        db,
        Agency,
        name=AGENCY_NAME,
        defaults={"timezone": "America/Chicago", "is_active": True},
    )
    users = seed_users(db, agency, password)
    carriers = seed_carriers(db, agency)
    agent_one = users["agent.one@demo.local"]
    agent_two = users["agent.two@demo.local"]

    americo_case = seed_case(
        db,
        agency=agency,
        carrier=carriers["Americo"],
        agent=agent_one,
        client_name="John Doe",
        policy_number="AMR-98765432",
        policy_status=PolicyStatus.PENDING,
        priority=Priority.HIGH,
        summary=(
            "Americo needs a signed HIPAA authorization and clarification of a "
            "prescription-history answer before underwriting can continue."
        ),
        deadline=datetime(2026, 8, 17, 22, 0, tzinfo=UTC),
    )
    americo_message = seed_message(
        db,
        agency=agency,
        case=americo_case,
        carrier=carriers["Americo"],
        fixture_id="demo-americo-pending-1",
        sender="requirements@americo.com",
        subject="Pending requirements for policy AMR-98765432",
        received_at=datetime(2026, 8, 3, 14, 30, tzinfo=UTC),
        classification=MessageClassification.PENDING_REQUIREMENTS,
        summary="Underwriting requires HIPAA authorization and prescription-history clarification.",
        priority=Priority.HIGH,
        deadline_text="within 10 business days",
        body=(
            "Policy AMR-98765432 for John Doe remains pending. Please obtain a signed "
            "HIPAA authorization and clarify the medical-history response related to the "
            "04/12/2026 prescription. Submit all requirements within 10 business days."
        ),
    )
    seed_task(
        db,
        agency=agency,
        case=americo_case,
        message=americo_message,
        agent=agent_one,
        title="Obtain signed HIPAA authorization",
        description="Contact John Doe and obtain the required signed authorization.",
        priority=Priority.HIGH,
        due_at=datetime(2026, 8, 12, 22, 0, tzinfo=UTC),
        status=TaskStatus.IN_PROGRESS,
    )
    seed_task(
        db,
        agency=agency,
        case=americo_case,
        message=americo_message,
        agent=agent_one,
        title="Clarify prescription history",
        description="Clarify the medical-history answer concerning the 04/12/2026 prescription.",
        priority=Priority.HIGH,
        due_at=datetime(2026, 8, 14, 22, 0, tzinfo=UTC),
    )
    seed_task(
        db,
        agency=agency,
        case=americo_case,
        message=americo_message,
        agent=agent_one,
        title="Submit pending requirements",
        description="Submit the completed requirements to Americo within the stated timeframe.",
        priority=Priority.HIGH,
        due_at=datetime(2026, 8, 17, 22, 0, tzinfo=UTC),
    )
    get_or_create(
        db,
        Attachment,
        carrier_message_id=americo_message.id,
        filename="pending-requirements.pdf",
        defaults={
            "external_id": "demo-attachment-americo",
            "mime_type": "application/pdf",
            "size_bytes": 84211,
            "processing_status": AttachmentStatus.EXTRACTED,
            "extracted_text": "Development fixture metadata; PDF retrieval is not implemented.",
        },
    )
    get_or_create(
        db,
        CaseEvidence,
        case_id=americo_case.id,
        field_name="current_policy_status",
        defaults={
            "carrier_message_id": americo_message.id,
            "attachment_id": None,
            "source_type": "EMAIL_BODY",
            "excerpt": "Policy AMR-98765432 for John Doe remains pending.",
            "created_at": datetime(2026, 8, 3, 14, 31, tzinfo=UTC),
        },
    )

    aetna_case = seed_case(
        db,
        agency=agency,
        carrier=carriers["Aetna"],
        agent=agent_two,
        client_name="Mary Smith",
        policy_number="ATN-554433221",
        policy_status=PolicyStatus.ISSUED,
        priority=Priority.NORMAL,
        summary=(
            "Aetna approved and mailed Mary Smith's policy; the first premium draft "
            "should be verified on the effective date."
        ),
        premium=Decimal("145.00"),
        effective_date=date(2026, 9, 1),
    )
    aetna_message = seed_message(
        db,
        agency=agency,
        case=aetna_case,
        carrier=carriers["Aetna"],
        fixture_id="demo-aetna-issued-1",
        sender="newbusiness@aetna.com",
        subject="Policy issued: ATN-554433221",
        received_at=datetime(2026, 8, 5, 13, 15, tzinfo=UTC),
        classification=MessageClassification.POLICY_ISSUED,
        summary="Policy approved and mailed with a September 1 effective date.",
        priority=Priority.NORMAL,
        body=(
            "Mary Smith's policy ATN-554433221 has been approved and mailed. "
            "Effective date is September 1, 2026. Monthly premium is $145.00."
        ),
    )
    seed_task(
        db,
        agency=agency,
        case=aetna_case,
        message=aetna_message,
        agent=agent_two,
        title="Notify client of policy approval",
        description="Tell Mary Smith that the policy was approved and mailed.",
        priority=Priority.NORMAL,
        due_at=datetime(2026, 8, 6, 22, 0, tzinfo=UTC),
        status=TaskStatus.COMPLETED,
    )
    seed_task(
        db,
        agency=agency,
        case=aetna_case,
        message=aetna_message,
        agent=agent_two,
        title="Verify first premium draft",
        description="Confirm the first $145.00 premium draft on the effective date.",
        priority=Priority.NORMAL,
        due_at=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
    )

    amam_case = seed_case(
        db,
        agency=agency,
        carrier=carriers["American Amicable / AMAM"],
        agent=agent_one,
        client_name="Robert Johnson",
        policy_number="AA-1122334",
        policy_status=PolicyStatus.GRACE_PERIOD,
        priority=Priority.URGENT,
        summary=(
            "A failed $89.50 payment placed the policy in its grace period; updated "
            "banking information is needed before September 15 to prevent lapse."
        ),
        premium=Decimal("89.50"),
        deadline=datetime(2026, 9, 15, 23, 59, tzinfo=UTC),
    )
    amam_message = seed_message(
        db,
        agency=agency,
        case=amam_case,
        carrier=carriers["American Amicable / AMAM"],
        fixture_id="demo-amam-lapse-1",
        sender="policyservice@americanamicable.com",
        subject="Grace period notice for AA-1122334",
        received_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        classification=MessageClassification.LAPSE_NOTICE,
        summary="The $89.50 premium payment was returned NSF and the policy is at risk of lapse.",
        priority=Priority.URGENT,
        deadline_text="before September 15, 2026",
        body=(
            "The $89.50 premium payment for Robert Johnson, policy AA-1122334, was "
            "returned NSF. Contact the client and update banking information before "
            "September 15, 2026 to prevent lapse."
        ),
    )
    seed_task(
        db,
        agency=agency,
        case=amam_case,
        message=amam_message,
        agent=agent_one,
        title="Contact client about failed payment",
        description="Discuss the returned $89.50 payment with Robert Johnson.",
        priority=Priority.URGENT,
        due_at=datetime(2026, 8, 11, 17, 0, tzinfo=UTC),
    )
    seed_task(
        db,
        agency=agency,
        case=amam_case,
        message=amam_message,
        agent=agent_one,
        title="Update banking information",
        description="Update banking information before the deadline to prevent lapse.",
        priority=Priority.URGENT,
        due_at=datetime(2026, 9, 15, 17, 0, tzinfo=UTC),
    )

    failed_message = seed_message(
        db,
        agency=agency,
        case=americo_case,
        carrier=carriers["Americo"],
        fixture_id="demo-americo-attachment-failure",
        sender="requirements@americo.com",
        subject="Supplemental underwriting attachment",
        received_at=datetime(2026, 8, 12, 15, 45, tzinfo=UTC),
        classification=MessageClassification.OTHER,
        summary="A supplemental attachment could not be interpreted and requires human review.",
        priority=Priority.HIGH,
        body="A supplemental underwriting document is attached.",
        status=ProcessingStatus.NEEDS_REVIEW,
    )
    failed_attachment = get_or_create(
        db,
        Attachment,
        carrier_message_id=failed_message.id,
        filename="supplemental-scan.pdf",
        defaults={
            "external_id": "demo-attachment-failure",
            "mime_type": "application/pdf",
            "size_bytes": 129443,
            "processing_status": AttachmentStatus.FAILED,
            "extracted_text": None,
        },
    )
    get_or_create(
        db,
        ReviewItem,
        carrier_message_id=failed_message.id,
        reason_code="ATTACHMENT_UNREADABLE",
        defaults={
            "agency_id": agency.id,
            "case_id": americo_case.id,
            "assigned_reviewer_id": agent_one.id,
            "status": ReviewStatus.OPEN,
            "reason": f"Attachment {failed_attachment.filename} could not be interpreted.",
        },
    )
    get_or_create(
        db,
        AuditEvent,
        agency_id=agency.id,
        event_type="PROCESSING_FAILED",
        description="Supplemental underwriting attachment requires manual review",
        defaults={
            "actor_user_id": None,
            "case_id": americo_case.id,
            "carrier_message_id": failed_message.id,
            "task_id": None,
            "severity": AuditSeverity.WARNING,
            "event_metadata": {"stage": "attachment_extraction", "safe_fixture": True},
            "created_at": datetime(2026, 8, 12, 15, 46, tzinfo=UTC),
        },
    )
    db.commit()


def main() -> None:
    settings = get_settings()
    if settings.environment != "development":
        raise SystemExit("Development seed is disabled outside the development environment.")
    if settings.demo_seed_password is None:
        raise SystemExit("DEMO_SEED_PASSWORD is required for the development seed.")
    with SessionLocal() as db:
        seed_demo_data(db, settings.demo_seed_password.get_secret_value())
    print("Development seed completed successfully.")


if __name__ == "__main__":
    main()
