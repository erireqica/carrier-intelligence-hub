from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pymupdf
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.integrations.ai.errors import AnalysisProviderError
from app.integrations.ai.schemas import (
    ActionItem,
    AnalysisResult,
    Deadline,
    Evidence,
    HumanAnalysisInput,
    InterpretationAmbiguity,
    InterpretationCandidate,
    SourceFact,
)
from app.integrations.gmail.errors import GmailReauthorizationRequired, GmailTransientError
from app.models.audit import AuditEvent
from app.models.carriers import Carrier
from app.models.enums import (
    AttachmentStatus,
    CaseAssignmentSource,
    GmailConnectionStatus,
    GmailLabelSyncStatus,
    MessageClassification,
    PolicyStatus,
    Priority,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
    UserRole,
)
from app.models.gmail_labels import GmailThreadLabelSync
from app.models.operations import (
    Attachment,
    CarrierMessage,
    CaseEvidence,
    MessageAnalysis,
    PolicyCase,
    ReviewItem,
    Task,
)
from app.models.organization import GmailConnection, GmailOAuthCredential, User
from app.services.auth import AuthContext, create_session
from app.services.message_processing import (
    ProcessingResult,
    apply_review,
    claim_message,
    manual_process,
    process_claimed_message,
    process_message,
    reconcile_stored_discrepancy_tasks,
    recover_stale_processing,
    reevaluate_stored_review,
)
from app.services.operations import get_case_detail
from app.workers.message_process import (
    _configure_shutdown_signals,
    process_once,
)


class FakeAnalyzer:
    model_name = "synthetic-stage4-model"

    def __init__(self, result: AnalysisResult | None = None, error: str | None = None):
        self.result = result
        self.error = error
        self.calls = 0
        self.last_source = ""

    def analyze(self, source_bundle: str) -> AnalysisResult:
        self.calls += 1
        self.last_source = source_bundle
        assert "AUTHORITATIVE CARRIER" in source_bundle
        if self.error:
            raise AnalysisProviderError(self.error)
        assert self.result is not None
        return self.result


def analysis_result(
    *,
    client: str = "Test Client",
    policy: str = "TEST-10001",
    confidence: float = 0.95,
) -> AnalysisResult:
    return AnalysisResult(
        classification=MessageClassification.PENDING_REQUIREMENTS,
        summary=f"Americo needs an authorization for {client}.",
        priority=Priority.HIGH,
        client_name=client,
        policy_number=policy,
        policy_status=PolicyStatus.PENDING,
        premium_amount=None,
        currency=None,
        effective_date=None,
        deadline=Deadline(
            raw_text="within 10 business days",
            explicit_date=None,
            relative_count=10,
            relative_unit="BUSINESS_DAYS",
        ),
        requirements=["signed authorization"],
        action_items=[
            ActionItem(
                title="Obtain signed authorization",
                description="Collect the requested authorization.",
                priority=Priority.HIGH,
                explicit_due_date=None,
                due_text="within 10 business days",
            )
        ],
        evidence=[
            Evidence(field_name="client_name", source_id="email", excerpt=f"Client: {client}"),
            Evidence(field_name="policy_number", source_id="email", excerpt=f"Policy: {policy}"),
            Evidence(field_name="policy_status", source_id="email", excerpt="Status: PENDING"),
            Evidence(
                field_name="deadline",
                source_id="email",
                excerpt="within 10 business days",
            ),
            Evidence(
                field_name="action_item:0",
                source_id="email",
                excerpt="signed authorization within 10 business days",
            ),
        ],
        overall_confidence=confidence,
        uncertainties=([] if confidence >= 0.7 else ["Synthetic critical-value ambiguity"]),
    )


def with_interpretation_ambiguity(result: AnalysisResult) -> AnalysisResult:
    excerpt = "Please return the signed authorization within 10 business days."
    return result.model_copy(
        update={
            "interpretation_ambiguities": [
                InterpretationAmbiguity(
                    field_name="requirement_association",
                    explanation=(
                        "The deadline can reasonably apply to either the authorization or all "
                        "outstanding requirements."
                    ),
                    candidates=[
                        InterpretationCandidate(
                            interpretation="The deadline applies only to the authorization.",
                            source_id="email",
                            excerpt=excerpt,
                        ),
                        InterpretationCandidate(
                            interpretation=(
                                "The deadline applies to every outstanding requirement."
                            ),
                            source_id="email",
                            excerpt=excerpt,
                        ),
                    ],
                )
            ]
        }
    )


def policy_issued_result(
    *,
    client: str,
    policy: str,
    premium: str,
    currency: str,
    status: PolicyStatus = PolicyStatus.ISSUED,
) -> AnalysisResult:
    return AnalysisResult(
        classification=MessageClassification.POLICY_ISSUED,
        summary=f"The carrier issued policy {policy} for {client}.",
        priority=Priority.NORMAL,
        client_name=client,
        policy_number=policy,
        policy_status=status,
        premium_amount=premium,
        currency=currency,
        effective_date="2026-08-28",
        deadline=Deadline(
            raw_text=None,
            explicit_date=None,
            relative_count=None,
            relative_unit=None,
        ),
        requirements=[],
        action_items=[],
        evidence=[
            Evidence(field_name="client_name", source_id="email", excerpt=f"Client Name: {client}"),
            Evidence(
                field_name="policy_number",
                source_id="email",
                excerpt=f"Policy Number: {policy}",
            ),
            Evidence(
                field_name="policy_status",
                source_id="email",
                excerpt=f"Policy Status: {status.value.title()}",
            ),
            Evidence(
                field_name="premium_amount",
                source_id="email",
                excerpt="Premium Amount: $1,250.00 USD",
            ),
            Evidence(
                field_name="effective_date",
                source_id="email",
                excerpt="Effective Date: August 28, 2026",
            ),
        ],
        overall_confidence=0.99,
        uncertainties=[],
    )


def create_received_message(
    db: Session,
    *,
    client: str,
    policy: str,
    subject_suffix: str,
    owner: User | None = None,
    gmail_address: str | None = None,
) -> CarrierMessage:
    owner = owner or db.scalar(select(User).where(User.role == UserRole.AGENT).order_by(User.id))
    carrier = db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    assert owner is not None and carrier is not None
    connection = GmailConnection(
        agency_id=owner.agency_id,
        user_id=owner.id,
        gmail_address=gmail_address or f"stage4-{subject_suffix}@gmail.test",
        status=GmailConnectionStatus.CONNECTED,
    )
    db.add(connection)
    db.flush()
    body = (
        f"Client: {client}\nPolicy: {policy}\nStatus: PENDING\n"
        "Please return the signed authorization within 10 business days."
    )
    message = CarrierMessage(
        agency_id=owner.agency_id,
        carrier_id=carrier.id,
        gmail_connection_id=connection.id,
        gmail_message_id=f"stage4-{subject_suffix}",
        gmail_thread_id=f"thread-stage4-{subject_suffix}",
        sender="development-sender@example.test",
        subject=f"Pending requirements {subject_suffix}",
        received_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        processing_status=ProcessingStatus.RECEIVED,
        raw_content=body,
        cleaned_content=body,
    )
    db.add(message)
    db.commit()
    return message


def add_policy_conflict_attachment(
    db: Session, message: CarrierMessage, *, conflicting_policy: str
) -> Attachment:
    attachment = Attachment(
        carrier_message_id=message.id,
        external_id=f"conflict-{message.gmail_message_id}",
        filename="conflicting-policy.pdf",
        mime_type="application/pdf",
        size_bytes=128,
        processing_status=AttachmentStatus.EXTRACTED,
        extracted_text=(
            f"Client: {message.cleaned_content.split('Client: ', 1)[1].splitlines()[0]}\n"
            f"Policy: {conflicting_policy}\nStatus: PENDING"
        ),
        extracted_at=datetime.now(UTC),
        page_count=1,
    )
    db.add(attachment)
    db.commit()
    return attachment


def auth_context(db: Session, user_id: int) -> AuthContext:
    user = db.get(User, user_id)
    assert user is not None
    session, _, csrf = create_session(db, user)
    db.commit()
    return AuthContext(user=user, agency=user.agency, session=session, csrf_token=csrf)


def add_pending_pdf_attachment(db: Session, message: CarrierMessage) -> Attachment:
    connection = db.get(GmailConnection, message.gmail_connection_id)
    assert connection is not None
    db.add(
        GmailOAuthCredential(
            gmail_connection_id=connection.id,
            encrypted_access_token="synthetic",
            encrypted_refresh_token="synthetic",
            granted_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
    )
    attachment = Attachment(
        carrier_message_id=message.id,
        external_id=f"attachment-{message.id}",
        filename="requirements.pdf",
        mime_type="application/pdf",
        size_bytes=2048,
        processing_status=AttachmentStatus.PENDING,
    )
    db.add(attachment)
    db.commit()
    return attachment


def test_strong_analysis_creates_case_tasks_evidence_and_is_idempotent(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db, client="Test Client", policy="TEST-10001", subject_suffix="success"
    )
    analyzer = FakeAnalyzer(analysis_result())

    first = process_message(
        seeded_db,
        message.id,
        analyzer=analyzer,
        settings=Settings(ai_auto_apply_confidence_threshold=0.8),
    )
    second = process_message(seeded_db, message.id, analyzer=analyzer)

    seeded_db.refresh(message)
    case = seeded_db.get(PolicyCase, first.case_id)
    assert case is not None
    assert first.processing_status is ProcessingStatus.PROCESSED
    assert message.processing_status is ProcessingStatus.PROCESSED
    assert message.carrier_id == case.carrier_id
    assert (case.client_name, case.policy_number, case.current_policy_status) == (
        "Test Client",
        "TEST-10001",
        PolicyStatus.PENDING,
    )
    assert analyzer.calls == 1
    assert second.processing_status is ProcessingStatus.PROCESSED
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.source_carrier_message_id == message.id)
        )
        == 1
    )
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(CaseEvidence)
            .where(CaseEvidence.carrier_message_id == message.id)
        )
        == 5
    )
    analysis = seeded_db.scalar(
        select(MessageAnalysis).where(MessageAnalysis.carrier_message_id == message.id)
    )
    assert analysis is not None
    assert analysis.model_result_json == analysis.final_result_json


def test_reprocessing_reconciles_stale_tasks_and_replaces_evidence(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Retry Reconciliation",
        policy="RETRY-RECONCILE-1",
        subject_suffix="retry-reconciliation",
    )
    initial = analysis_result(client="Retry Reconciliation", policy="RETRY-RECONCILE-1")
    second_action = ActionItem(
        title="Confirm receipt with carrier",
        description="Confirm the carrier received the authorization.",
        priority=Priority.NORMAL,
        explicit_due_date=None,
        due_text=None,
    )
    initial = initial.model_copy(
        update={
            "action_items": [*initial.action_items, second_action],
            "evidence": [
                *initial.evidence,
                Evidence(
                    field_name="action_item:1",
                    source_id="email",
                    excerpt="signed authorization within 10 business days",
                ),
            ],
        }
    )
    process_message(seeded_db, message.id, analyzer=FakeAnalyzer(initial))
    first_evidence_ids = set(
        seeded_db.scalars(
            select(CaseEvidence.id).where(CaseEvidence.carrier_message_id == message.id)
        ).all()
    )
    message.processing_status = ProcessingStatus.FAILED
    message.last_processing_error_code = "MATERIALIZATION_FAILED"
    seeded_db.commit()

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(
            analysis_result(client="Retry Reconciliation", policy="RETRY-RECONCILE-1")
        ),
    )

    tasks = seeded_db.scalars(
        select(Task)
        .where(Task.source_carrier_message_id == message.id)
        .order_by(Task.source_action_index)
    ).all()
    evidence = seeded_db.scalars(
        select(CaseEvidence).where(CaseEvidence.carrier_message_id == message.id)
    ).all()
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert [(task.source_action_index, task.status) for task in tasks] == [
        (0, TaskStatus.OPEN),
        (1, TaskStatus.DISMISSED),
    ]
    assert len(evidence) == 5
    assert first_evidence_ids.isdisjoint({item.id for item in evidence})


def test_reprocessing_never_reconciles_a_manual_task_by_matching_title(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Manual Task Safety",
        policy="MANUAL-SAFE-1",
        subject_suffix="manual-task-reprocessing",
    )
    initial = analysis_result(client="Manual Task Safety", policy="MANUAL-SAFE-1")
    process_message(seeded_db, message.id, analyzer=FakeAnalyzer(initial))
    seeded_db.refresh(message)
    policy_case = seeded_db.get(PolicyCase, message.case_id)
    assert policy_case is not None and policy_case.assigned_agent_id is not None
    manual = Task(
        agency_id=message.agency_id,
        case_id=policy_case.id,
        assigned_agent_id=policy_case.assigned_agent_id,
        created_by_user_id=policy_case.assigned_agent_id,
        title="Obtain premium amount from carrier",
        description="Agent-authored notes that AI reconciliation must preserve.",
        priority=Priority.URGENT,
        due_at=datetime(2026, 9, 1, 22, 0, tzinfo=UTC),
        status=TaskStatus.IN_PROGRESS,
    )
    seeded_db.add(manual)
    seeded_db.commit()
    original = (
        manual.title,
        manual.description,
        manual.priority,
        manual.due_at,
        manual.status,
        manual.assigned_agent_id,
        manual.created_by_user_id,
    )

    missing_action = ActionItem(
        title=manual.title,
        description="AI-generated carrier follow-up.",
        priority=Priority.NORMAL,
        explicit_due_date=None,
        due_text=None,
    )
    retried = initial.model_copy(update={"action_items": [*initial.action_items, missing_action]})
    message.processing_status = ProcessingStatus.FAILED
    message.last_processing_error_code = "MATERIALIZATION_FAILED"
    seeded_db.commit()
    process_message(seeded_db, message.id, analyzer=FakeAnalyzer(retried))

    seeded_db.refresh(manual)
    assert (
        manual.title,
        manual.description,
        manual.priority,
        manual.due_at,
        manual.status,
        manual.assigned_agent_id,
        manual.created_by_user_id,
    ) == original
    assert manual.source_carrier_message_id is None
    generated = seeded_db.scalar(
        select(Task).where(
            Task.source_carrier_message_id == message.id,
            Task.title == missing_action.title,
        )
    )
    assert generated is not None and generated.id != manual.id


def test_pdf_attachment_is_downloaded_in_memory_extracted_and_joined_to_source(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="PDF Client",
        policy="PDF-100",
        subject_suffix="pdf",
    )
    connection = seeded_db.get(GmailConnection, message.gmail_connection_id)
    assert connection is not None
    seeded_db.add(
        GmailOAuthCredential(
            gmail_connection_id=connection.id,
            encrypted_access_token="synthetic",
            encrypted_refresh_token="synthetic",
            granted_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
    )
    attachment = Attachment(
        carrier_message_id=message.id,
        external_id="pdf-attachment-1",
        filename="requirements.pdf",
        mime_type="application/pdf",
        size_bytes=2048,
        processing_status=AttachmentStatus.PENDING,
    )
    seeded_db.add(attachment)
    seeded_db.commit()
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Synthetic PDF requirement for policy PDF-100")
    content = document.tobytes()
    document.close()

    class AttachmentMailbox:
        def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
            assert message_id == message.gmail_message_id
            assert attachment_id == attachment.external_id
            return content

    analyzer = FakeAnalyzer(analysis_result(client="PDF Client", policy="PDF-100"))
    result = process_message(
        seeded_db,
        message.id,
        analyzer=analyzer,
        mailbox_factory=lambda credential: (AttachmentMailbox(), False),
    )

    seeded_db.refresh(attachment)
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.attachments_extracted == 1
    assert attachment.processing_status is AttachmentStatus.EXTRACTED
    assert attachment.page_count == 1
    assert "Synthetic PDF requirement" in (attachment.extracted_text or "")
    assert "Synthetic PDF requirement" in analyzer.last_source


def test_attachment_reauthorization_pauses_processing_until_reconnect(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Reauthorization Client",
        policy="REAUTH-100",
        subject_suffix="attachment-reauth",
    )
    attachment = add_pending_pdf_attachment(seeded_db, message)
    other_message = create_received_message(
        seeded_db,
        client="Other Connection Client",
        policy="OTHER-100",
        subject_suffix="other-connection",
    )
    connection = seeded_db.get(GmailConnection, message.gmail_connection_id)
    other_connection = seeded_db.get(GmailConnection, other_message.gmail_connection_id)
    assert connection is not None and other_connection is not None

    class ReauthorizationMailbox:
        def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
            raise GmailReauthorizationRequired("synthetic secret provider detail")

    analyzer = FakeAnalyzer(analysis_result(client="Reauthorization Client", policy="REAUTH-100"))
    failed = process_message(
        seeded_db,
        message.id,
        analyzer=analyzer,
        settings=Settings(message_process_max_auto_attempts=3),
        mailbox_factory=lambda credential: (ReauthorizationMailbox(), False),
    )

    seeded_db.refresh(message)
    seeded_db.refresh(attachment)
    seeded_db.refresh(connection)
    seeded_db.refresh(other_connection)
    assert failed.processing_status is ProcessingStatus.FAILED
    assert message.last_processing_error_code == "GMAIL_REAUTH_REQUIRED"
    assert message.processing_next_retry_at is None
    assert attachment.processing_status is AttachmentStatus.PENDING
    assert connection.status is GmailConnectionStatus.NEEDS_REAUTH
    assert other_connection.status is GmailConnectionStatus.CONNECTED
    assert analyzer.calls == 0
    assert message.case_id is None
    assert message.raw_content.startswith("Client: Reauthorization Client")
    assert message.cleaned_content.startswith("Client: Reauthorization Client")
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.source_carrier_message_id == message.id)
        )
        == 0
    )
    assert claim_message(seeded_db, message_id=message.id) is None
    event = seeded_db.scalar(
        select(AuditEvent).where(
            AuditEvent.carrier_message_id == message.id,
            AuditEvent.event_type == "GMAIL_REAUTH_REQUIRED",
        )
    )
    assert event is not None
    assert event.event_metadata == {
        "connection_id": connection.id,
        "error_code": "GMAIL_REAUTH_REQUIRED",
    }
    assert "secret" not in event.description.lower()
    assert "secret" not in str(event.event_metadata).lower()

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Recovered PDF requirement for policy REAUTH-100")
    content = document.tobytes()
    document.close()

    class ReconnectedMailbox:
        def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
            return content

    connection.status = GmailConnectionStatus.CONNECTED
    connection.last_error_summary = None
    seeded_db.commit()
    succeeded = process_message(
        seeded_db,
        message.id,
        analyzer=analyzer,
        mailbox_factory=lambda credential: (ReconnectedMailbox(), False),
    )

    seeded_db.refresh(message)
    seeded_db.refresh(attachment)
    assert succeeded.processing_status is ProcessingStatus.PROCESSED
    assert message.processing_attempt_count == 2
    assert attachment.processing_status is AttachmentStatus.EXTRACTED
    assert analyzer.calls == 1


def test_transient_attachment_failure_keeps_automatic_retry_semantics(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Transient Client",
        policy="TRANSIENT-100",
        subject_suffix="attachment-transient",
    )
    add_pending_pdf_attachment(seeded_db, message)
    connection = seeded_db.get(GmailConnection, message.gmail_connection_id)
    assert connection is not None

    class TransientMailbox:
        def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
            raise GmailTransientError("synthetic provider outage")

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(analysis_result(client="Transient Client", policy="TRANSIENT-100")),
        settings=Settings(message_process_max_auto_attempts=3),
        mailbox_factory=lambda credential: (TransientMailbox(), False),
    )

    seeded_db.refresh(message)
    seeded_db.refresh(connection)
    assert result.processing_status is ProcessingStatus.FAILED
    assert message.last_processing_error_code == "ATTACHMENT_DOWNLOAD_FAILED"
    assert message.processing_next_retry_at is not None
    assert connection.status is GmailConnectionStatus.CONNECTED


def test_existing_case_client_mismatch_creates_external_verification_task(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Different Client",
        policy="AMR-98765432",
        subject_suffix="mismatch",
    )
    analyzer = FakeAnalyzer(analysis_result(client="Different Client", policy="AMR-98765432"))

    first = process_message(seeded_db, message.id, analyzer=analyzer)
    second = process_message(seeded_db, message.id, analyzer=analyzer)

    seeded_db.refresh(message)
    existing = seeded_db.scalar(
        select(PolicyCase).where(PolicyCase.policy_number == "AMR-98765432")
    )
    assert existing is not None and existing.client_name == "John Doe"
    assert first.processing_status is ProcessingStatus.PROCESSED
    assert first.validation_flags == ()
    assert second.processing_status is ProcessingStatus.PROCESSED
    assert analyzer.calls == 1
    reviews = seeded_db.scalars(
        select(ReviewItem).where(ReviewItem.carrier_message_id == message.id)
    ).all()
    assert reviews == []
    tasks = seeded_db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()
    assert [task.title for task in tasks].count("Verify client identity with carrier") == 1


def test_existing_case_is_reused_preserves_assignment_and_known_non_null_values(
    seeded_db: Session,
) -> None:
    existing = seeded_db.scalar(
        select(PolicyCase).where(PolicyCase.policy_number == "AMR-98765432")
    )
    assert existing is not None
    original_assignee = existing.assigned_agent_id
    existing.premium_amount = Decimal("321.00")
    existing.currency = "USD"
    seeded_db.commit()
    case_count = seeded_db.scalar(select(func.count()).select_from(PolicyCase))
    message = create_received_message(
        seeded_db,
        client="John Doe",
        policy="AMR-98765432",
        subject_suffix="existing-update",
    )

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(analysis_result(client="John Doe", policy="AMR-98765432")),
    )

    seeded_db.refresh(existing)
    seeded_db.refresh(message)
    assert result.case_id == existing.id
    assert seeded_db.scalar(select(func.count()).select_from(PolicyCase)) == case_count
    assert existing.assigned_agent_id == original_assignee
    assert existing.premium_amount == Decimal("321.00")
    assert existing.currency == "USD"
    assert message.case_id == existing.id
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.source_carrier_message_id == message.id)
        )
        == 1
    )


def test_same_mailbox_handoff_transfers_case_and_only_active_work(
    seeded_db: Session,
) -> None:
    agents = seeded_db.scalars(
        select(User).where(User.role == UserRole.AGENT).order_by(User.id)
    ).all()
    manager = seeded_db.scalar(select(User).where(User.role == UserRole.MANAGER))
    existing = seeded_db.scalar(
        select(PolicyCase).where(PolicyCase.policy_number == "AMR-98765432")
    )
    assert len(agents) == 2 and manager is not None and existing is not None
    former_owner, new_owner = agents
    historical = GmailConnection(
        agency_id=existing.agency_id,
        user_id=former_owner.id,
        gmail_address="shared-handoff@gmail.test",
        status=GmailConnectionStatus.DISCONNECTED,
    )
    seeded_db.add(historical)
    seeded_db.flush()
    historical_message = seeded_db.scalar(
        select(CarrierMessage)
        .where(CarrierMessage.case_id == existing.id)
        .order_by(CarrierMessage.id)
    )
    assert historical_message is not None
    historical_message.gmail_connection_id = historical.id
    completed = Task(
        agency_id=existing.agency_id,
        case_id=existing.id,
        assigned_agent_id=former_owner.id,
        created_by_user_id=former_owner.id,
        completed_by_user_id=former_owner.id,
        title="Historical completed handoff task",
        priority=Priority.NORMAL,
        status=TaskStatus.COMPLETED,
        completed_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    manual = Task(
        agency_id=existing.agency_id,
        case_id=existing.id,
        assigned_agent_id=former_owner.id,
        created_by_user_id=former_owner.id,
        title="Call client to confirm mailing address",
        description="Manually added work must follow active Case ownership.",
        priority=Priority.NORMAL,
        status=TaskStatus.OPEN,
    )
    resolved = ReviewItem(
        agency_id=existing.agency_id,
        case_id=existing.id,
        carrier_message_id=historical_message.id,
        assigned_reviewer_id=former_owner.id,
        status=ReviewStatus.RESOLVED,
        reason_code="HISTORICAL_REVIEW",
        reason="Historical resolved review",
        resolved_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    seeded_db.add_all([completed, manual, resolved])
    seeded_db.commit()
    legacy_message = create_received_message(
        seeded_db,
        client="John Doe",
        policy="AMR-98765432",
        subject_suffix="legacy-conflict-before-handoff",
        owner=new_owner,
        gmail_address="different-handoff-inbox@gmail.test",
    )
    legacy_result = process_message(
        seeded_db,
        legacy_message.id,
        analyzer=FakeAnalyzer(analysis_result(client="John Doe", policy="AMR-98765432")),
    )
    assert legacy_result.processing_status is ProcessingStatus.PROCESSED
    legacy_review = ReviewItem(
        agency_id=existing.agency_id,
        case_id=None,
        carrier_message_id=legacy_message.id,
        assigned_reviewer_id=new_owner.id,
        status=ReviewStatus.OPEN,
        reason_code="CASE_OWNER_CONFLICT",
        reason="Legacy mailbox-owner conflict",
    )
    seeded_db.add(legacy_review)
    legacy_message.case_id = None
    legacy_message.processing_status = ProcessingStatus.NEEDS_REVIEW
    assert legacy_message.analysis is not None
    legacy_message.analysis.validation_flags = ["CASE_OWNER_CONFLICT"]
    seeded_db.commit()
    message = create_received_message(
        seeded_db,
        client="John Doe",
        policy="AMR-98765432",
        subject_suffix="same-mailbox-handoff",
        owner=new_owner,
        gmail_address="SHARED-HANDOFF@gmail.test",
    )
    with pytest.raises(HTTPException) as not_yet_transferred:
        get_case_detail(seeded_db, auth_context(seeded_db, new_owner.id), existing.id)
    assert not_yet_transferred.value.status_code == 404

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(analysis_result(client="John Doe", policy="AMR-98765432")),
    )

    seeded_db.refresh(existing)
    seeded_db.refresh(completed)
    seeded_db.refresh(manual)
    seeded_db.refresh(resolved)
    seeded_db.refresh(legacy_message)
    seeded_db.refresh(legacy_review)
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.case_id == existing.id
    assert existing.assigned_agent_id == new_owner.id
    assert existing.assignment_source is CaseAssignmentSource.GMAIL_HANDOFF
    assert completed.assigned_agent_id == former_owner.id
    assert completed.status is TaskStatus.COMPLETED
    assert completed.created_by_user_id == former_owner.id
    assert completed.completed_by_user_id == former_owner.id
    assert manual.assigned_agent_id == new_owner.id
    assert manual.created_by_user_id == former_owner.id
    assert manual.source_carrier_message_id is None
    assert resolved.assigned_reviewer_id == former_owner.id
    assert resolved.status is ReviewStatus.RESOLVED
    assert legacy_message.case_id == existing.id
    assert legacy_message.processing_status is ProcessingStatus.PROCESSED
    assert legacy_review.case_id == existing.id
    assert legacy_review.assigned_reviewer_id == new_owner.id
    assert legacy_review.status is ReviewStatus.RESOLVED
    active_tasks = seeded_db.scalars(
        select(Task).where(
            Task.case_id == existing.id,
            Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
        )
    ).all()
    assert active_tasks and all(task.assigned_agent_id == new_owner.id for task in active_tasks)
    active_reviews = seeded_db.scalars(
        select(ReviewItem).where(
            ReviewItem.case_id == existing.id,
            ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
        )
    ).all()
    assert all(review.assigned_reviewer_id == new_owner.id for review in active_reviews)
    transfer = seeded_db.scalar(
        select(AuditEvent).where(
            AuditEvent.case_id == existing.id,
            AuditEvent.event_type == "CASE_OWNERSHIP_TRANSFERRED",
        )
    )
    assert transfer is not None
    with pytest.raises(HTTPException) as denied:
        get_case_detail(seeded_db, auth_context(seeded_db, former_owner.id), existing.id)
    assert denied.value.status_code == 404
    assert (
        get_case_detail(seeded_db, auth_context(seeded_db, new_owner.id), existing.id).id
        == existing.id
    )
    assert (
        get_case_detail(seeded_db, auth_context(seeded_db, manager.id), existing.id).id
        == existing.id
    )


def test_different_mailbox_policy_match_preserves_case_owner_and_gmail_provenance(
    seeded_db: Session,
) -> None:
    agents = seeded_db.scalars(
        select(User).where(User.role == UserRole.AGENT).order_by(User.id)
    ).all()
    existing = seeded_db.scalar(
        select(PolicyCase).where(PolicyCase.policy_number == "AMR-98765432")
    )
    assert len(agents) == 2 and existing is not None
    former_owner_id = existing.assigned_agent_id
    message = create_received_message(
        seeded_db,
        client="John Doe",
        policy="AMR-98765432",
        subject_suffix="different-mailbox-conflict",
        owner=agents[1],
        gmail_address="unrelated-inbox@gmail.test",
    )

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(analysis_result(client="John Doe", policy="AMR-98765432")),
    )

    seeded_db.refresh(existing)
    seeded_db.refresh(message)
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.case_id == existing.id
    assert result.validation_flags == ()
    assert result.review_id is None
    assert message.case_id == existing.id
    connection = seeded_db.get(GmailConnection, message.gmail_connection_id)
    assert connection is not None and connection.user_id == agents[1].id
    assert existing.assigned_agent_id == former_owner_id
    tasks = seeded_db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()
    assert tasks and all(task.assigned_agent_id == former_owner_id for task in tasks)


def test_case_linked_active_review_uses_case_owner_not_stale_reviewer(
    client: TestClient, seeded_db: Session, login
) -> None:
    agents = seeded_db.scalars(
        select(User).where(User.role == UserRole.AGENT).order_by(User.id)
    ).all()
    existing = seeded_db.scalar(
        select(PolicyCase).where(PolicyCase.policy_number == "AMR-98765432")
    )
    assert len(agents) == 2 and existing is not None
    case_owner = seeded_db.get(User, existing.assigned_agent_id)
    gmail_owner = next(agent for agent in agents if agent.id != existing.assigned_agent_id)
    assert case_owner is not None
    message = create_received_message(
        seeded_db,
        client="John Doe",
        policy="AMR-98765432",
        subject_suffix="stale-reviewer-scope",
        owner=gmail_owner,
        gmail_address="stale-reviewer@gmail.test",
    )
    proposed = analysis_result(client="John Doe", policy="AMR-98765432")
    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))
    assert result.processing_status is ProcessingStatus.PROCESSED
    review = ReviewItem(
        agency_id=existing.agency_id,
        case_id=existing.id,
        carrier_message_id=message.id,
        assigned_reviewer_id=gmail_owner.id,
        status=ReviewStatus.OPEN,
        reason_code="CASE_OWNER_CONFLICT",
        reason="Legacy stale ownership review",
    )
    seeded_db.add(review)
    message.processing_status = ProcessingStatus.NEEDS_REVIEW
    seeded_db.commit()

    gmail_auth = login(client, gmail_owner.email)
    gmail_headers = {"X-CSRF-Token": gmail_auth["csrf_token"]}
    assert review.id not in {item["id"] for item in client.get("/api/v1/reviews").json()["items"]}
    assert client.get(f"/api/v1/reviews/{review.id}").status_code == 404
    assert client.get(f"/api/v1/reviews/{review.id}/analysis").status_code == 404
    correction = proposed.model_dump(
        mode="json",
        exclude={
            "evidence",
            "source_facts",
            "interpretation_ambiguities",
            "overall_confidence",
            "uncertainties",
        },
    )
    assert (
        client.post(
            f"/api/v1/reviews/{review.id}/apply-analysis",
            json=correction,
            headers=gmail_headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/reviews/{review.id}/dismiss-analysis",
            json={"resolution_notes": "Must not be accepted"},
            headers=gmail_headers,
        ).status_code
        == 404
    )

    case_auth = login(client, case_owner.email)
    case_headers = {"X-CSRF-Token": case_auth["csrf_token"]}
    assert review.id in {item["id"] for item in client.get("/api/v1/reviews").json()["items"]}
    assert client.get(f"/api/v1/reviews/{review.id}").status_code == 200
    assert client.get(f"/api/v1/reviews/{review.id}/analysis").status_code == 200
    resolved_response = client.post(
        f"/api/v1/reviews/{review.id}/apply-analysis",
        json=correction,
        headers=case_headers,
    )
    assert resolved_response.status_code == 200
    seeded_db.refresh(existing)
    seeded_db.refresh(review)
    assert existing.assigned_agent_id == case_owner.id
    assert review.status is ReviewStatus.RESOLVED

    manager_auth = login(client, "manager@demo.local")
    manager_headers = {"X-CSRF-Token": manager_auth["csrf_token"]}
    assert review.id in {
        item["id"]
        for item in client.get("/api/v1/reviews?view=RESOLVED&page_size=100").json()["items"]
    }
    assert client.get(f"/api/v1/reviews/{review.id}/analysis").status_code == 200
    assert (
        client.post(
            f"/api/v1/reviews/{review.id}/apply-analysis",
            json=correction,
            headers=manager_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/reviews/{review.id}/dismiss-analysis",
            json={"resolution_notes": "Managers are read-only"},
            headers=manager_headers,
        ).status_code
        == 403
    )
    case_auth = login(client, case_owner.email)
    case_headers = {"X-CSRF-Token": case_auth["csrf_token"]}
    assert (
        client.post(
            f"/api/v1/reviews/{review.id}/dismiss-analysis",
            json={"resolution_notes": "Current Case owner completed the review"},
            headers=case_headers,
        ).status_code
        == 409
    )


def test_unlinked_active_review_uses_assigned_reviewer_without_widening_message_access(
    client: TestClient, seeded_db: Session, login
) -> None:
    message = create_received_message(
        seeded_db,
        client="Unlinked Review Client",
        policy="UNLINKED-REVIEW-1",
        subject_suffix="unlinked-review-scope",
    )
    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(
            with_interpretation_ambiguity(
                analysis_result(
                    client="Unlinked Review Client",
                    policy="UNLINKED-REVIEW-1",
                    confidence=0.4,
                )
            )
        ),
    )
    review = seeded_db.get(ReviewItem, result.review_id)
    assigned = seeded_db.scalar(select(User).where(User.email == "agent.two@demo.local"))
    assert review is not None and assigned is not None and review.case_id is None
    review.assigned_reviewer_id = assigned.id
    seeded_db.commit()

    login(client, "agent.one@demo.local")
    assert review.id not in {item["id"] for item in client.get("/api/v1/reviews").json()["items"]}
    assert client.get(f"/api/v1/reviews/{review.id}/analysis").status_code == 404

    assigned_auth = login(client, assigned.email)
    assigned_headers = {"X-CSRF-Token": assigned_auth["csrf_token"]}
    assert review.id in {item["id"] for item in client.get("/api/v1/reviews").json()["items"]}
    assert client.get(f"/api/v1/reviews/{review.id}/analysis").status_code == 200
    assert client.get(f"/api/v1/carrier-messages/{message.id}/analysis").status_code == 404
    dismissed = client.post(
        f"/api/v1/reviews/{review.id}/dismiss-analysis",
        json={"resolution_notes": "Synthetic unlinked review dismissed"},
        headers=assigned_headers,
    )
    assert dismissed.status_code == 200


@pytest.mark.parametrize("confidence, expected_status", [(0.95, "RESOLVED"), (0.4, "RESOLVED")])
def test_manager_resave_reconciles_legacy_unlinked_owner_conflict_from_stored_analysis(
    client: TestClient,
    seeded_db: Session,
    login,
    monkeypatch,
    confidence: float,
    expected_status: str,
) -> None:
    agents = seeded_db.scalars(
        select(User).where(User.role == UserRole.AGENT).order_by(User.id)
    ).all()
    existing = seeded_db.scalar(
        select(PolicyCase).where(PolicyCase.policy_number == "AMR-98765432")
    )
    assert len(agents) == 2 and existing is not None
    case_owner = seeded_db.get(User, existing.assigned_agent_id)
    gmail_owner = next(agent for agent in agents if agent.id != existing.assigned_agent_id)
    assert case_owner is not None
    message = create_received_message(
        seeded_db,
        client="John Doe",
        policy="AMR-98765432",
        subject_suffix=f"legacy-owner-conflict-{confidence}",
        owner=gmail_owner,
        gmail_address=f"legacy-owner-conflict-{confidence}@gmail.test",
    )
    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(
            analysis_result(client="John Doe", policy="AMR-98765432", confidence=confidence)
        ),
    )
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert message.analysis is not None
    review = ReviewItem(
        agency_id=existing.agency_id,
        case_id=None,
        carrier_message_id=message.id,
        assigned_reviewer_id=gmail_owner.id,
        status=ReviewStatus.OPEN,
        reason_code="CASE_OWNER_CONFLICT",
        reason="Legacy mailbox-owner conflict",
    )
    seeded_db.add(review)
    message.case_id = None
    message.processing_status = ProcessingStatus.NEEDS_REVIEW
    message.analysis.validation_flags = ["CASE_OWNER_CONFLICT"]
    message.analysis.model_result_json = {
        key: value
        for key, value in message.analysis.model_result_json.items()
        if key not in {"source_facts", "interpretation_ambiguities"}
    }
    seeded_db.commit()
    monkeypatch.setattr(
        "app.services.message_processing.OpenAIAnalyzer",
        lambda *_args, **_kwargs: pytest.fail("Reconciliation must not invoke OpenAI"),
    )

    manager = login(client, "manager@demo.local")
    response = client.patch(
        f"/api/v1/cases/{existing.id}/assignment",
        json={"assigned_agent_id": case_owner.id},
        headers={"X-CSRF-Token": manager["csrf_token"]},
    )
    assert response.status_code == 200
    seeded_db.refresh(message)
    seeded_db.refresh(review)
    seeded_db.refresh(existing)
    assert existing.assigned_agent_id == case_owner.id
    assert message.case_id == existing.id
    assert review.case_id == existing.id
    assert review.assigned_reviewer_id == case_owner.id
    assert review.status.value == expected_status
    if expected_status == "RESOLVED":
        assert message.processing_status is ProcessingStatus.PROCESSED
        assert message.analysis.validation_flags == []
        tasks = seeded_db.scalars(
            select(Task).where(Task.source_carrier_message_id == message.id)
        ).all()
        assert tasks and all(task.assigned_agent_id == case_owner.id for task in tasks)
        label_sync = seeded_db.scalar(
            select(GmailThreadLabelSync).where(
                GmailThreadLabelSync.gmail_connection_id == message.gmail_connection_id,
                GmailThreadLabelSync.gmail_thread_id == message.gmail_thread_id,
            )
        )
        assert label_sync is not None
        assert label_sync.status is GmailLabelSyncStatus.PENDING


def test_manager_case_assignment_remains_authoritative_for_future_gmail_messages(
    seeded_db: Session,
) -> None:
    agents = seeded_db.scalars(
        select(User).where(User.role == UserRole.AGENT).order_by(User.id)
    ).all()
    existing = seeded_db.scalar(
        select(PolicyCase).where(PolicyCase.policy_number == "AMR-98765432")
    )
    assert len(agents) == 2 and existing is not None
    gmail_owner, assigned_agent = agents
    existing.assigned_agent_id = assigned_agent.id
    existing.assignment_source = CaseAssignmentSource.MANAGER
    for task in existing.tasks:
        if task.status in {TaskStatus.OPEN, TaskStatus.IN_PROGRESS}:
            task.assigned_agent_id = assigned_agent.id
    seeded_db.commit()
    message = create_received_message(
        seeded_db,
        client="John Doe",
        policy="AMR-98765432",
        subject_suffix="manager-assignment-authoritative",
        owner=gmail_owner,
        gmail_address="originating-agent@gmail.test",
    )

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(analysis_result(client="John Doe", policy="AMR-98765432")),
    )

    seeded_db.refresh(existing)
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.case_id == existing.id
    assert "CASE_OWNER_CONFLICT" not in result.validation_flags
    assert existing.assigned_agent_id == assigned_agent.id
    assert existing.assignment_source is CaseAssignmentSource.MANAGER
    new_tasks = seeded_db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()
    assert new_tasks and all(task.assigned_agent_id == assigned_agent.id for task in new_tasks)


def test_legacy_manager_mailbox_cannot_create_manager_owned_operational_work(
    seeded_db: Session,
) -> None:
    manager = seeded_db.scalar(select(User).where(User.role == UserRole.MANAGER))
    assert manager is not None
    message = create_received_message(
        seeded_db,
        client="Manager Mailbox Client",
        policy="MANAGER-MAILBOX-1",
        subject_suffix="manager-mailbox",
        owner=manager,
        gmail_address="legacy-manager@gmail.test",
    )

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(
            analysis_result(client="Manager Mailbox Client", policy="MANAGER-MAILBOX-1")
        ),
    )

    review = seeded_db.get(ReviewItem, result.review_id)
    assert result.processing_status is ProcessingStatus.NEEDS_REVIEW
    assert result.case_id is None
    assert "OPERATIONAL_OWNER_REQUIRED" in result.validation_flags
    assert review is not None and review.assigned_reviewer_id is None
    assert not seeded_db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()


def test_low_confidence_review_can_be_corrected_and_applied(seeded_db: Session) -> None:
    message = create_received_message(
        seeded_db, client="Review Client", policy="TEST-REVIEW-1", subject_suffix="review"
    )
    proposed = with_interpretation_ambiguity(
        analysis_result(client="Review Client", policy="TEST-REVIEW-1", confidence=0.4)
    )
    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))
    review = seeded_db.get(ReviewItem, result.review_id)
    assert review is not None
    label_sync = seeded_db.scalar(
        select(GmailThreadLabelSync).where(
            GmailThreadLabelSync.gmail_connection_id == message.gmail_connection_id,
            GmailThreadLabelSync.gmail_thread_id == message.gmail_thread_id,
        )
    )
    assert label_sync is not None
    review_generation = label_sync.generation
    message.analysis.model_result_json = {
        key: value
        for key, value in message.analysis.model_result_json.items()
        if key not in {"source_facts", "interpretation_ambiguities"}
    }
    seeded_db.commit()
    original_json = dict(message.analysis.model_result_json)
    correction = HumanAnalysisInput(
        **proposed.model_dump(
            exclude={
                "evidence",
                "source_facts",
                "interpretation_ambiguities",
                "overall_confidence",
                "uncertainties",
            }
        )
    )
    context = auth_context(seeded_db, review.assigned_reviewer_id)

    finalized = apply_review(seeded_db, context, review.id, correction)

    seeded_db.refresh(review)
    seeded_db.refresh(message)
    assert finalized.processing_status is ProcessingStatus.PROCESSED
    assert review.status is ReviewStatus.RESOLVED
    assert review.case_id == finalized.case_id
    assert message.processing_status is ProcessingStatus.PROCESSED
    assert message.analysis.model_result_json == original_json
    assert message.analysis.final_result_json is not None
    assert message.analysis.finalized_by_user_id == context.user.id
    seeded_db.refresh(label_sync)
    assert label_sync.status is GmailLabelSyncStatus.PENDING
    assert label_sync.generation == review_generation + 1
    evidence_fields = set(
        seeded_db.scalars(
            select(CaseEvidence.field_name).where(CaseEvidence.carrier_message_id == message.id)
        ).all()
    )
    assert {"client_name", "policy_number", "action_item:0"} <= evidence_fields


def test_human_corrections_drop_stale_identity_and_action_evidence(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Original Client",
        policy="ORIGINAL-100",
        subject_suffix="corrected-evidence",
    )
    proposed = with_interpretation_ambiguity(
        analysis_result(client="Original Client", policy="ORIGINAL-100", confidence=0.4)
    )
    processed = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))
    review = seeded_db.get(ReviewItem, processed.review_id)
    assert review is not None
    changed_action = proposed.action_items[0].model_copy(
        update={"title": "Call the corrected client"}
    )
    correction = HumanAnalysisInput(
        **proposed.model_dump(
            exclude={
                "evidence",
                "source_facts",
                "interpretation_ambiguities",
                "overall_confidence",
                "uncertainties",
                "action_items",
                "client_name",
                "policy_number",
            }
        ),
        client_name="Corrected Client",
        policy_number="CORRECTED-200",
        action_items=[changed_action],
    )
    context = auth_context(seeded_db, review.assigned_reviewer_id)

    finalized = apply_review(seeded_db, context, review.id, correction)

    evidence_fields = set(
        seeded_db.scalars(
            select(CaseEvidence.field_name).where(CaseEvidence.carrier_message_id == message.id)
        ).all()
    )
    assert finalized.processing_status is ProcessingStatus.PROCESSED
    assert "client_name" not in evidence_fields
    assert "policy_number" not in evidence_fields
    assert "action_item:0" not in evidence_fields


def test_provider_failure_is_failed_and_claim_is_single_use(seeded_db: Session) -> None:
    message = create_received_message(
        seeded_db, client="Failure Client", policy="TEST-FAIL-1", subject_suffix="failure"
    )
    first_claim = claim_message(seeded_db, message_id=message.id)
    second_claim = claim_message(seeded_db, message_id=message.id)
    assert first_claim == message.id
    assert second_claim is None

    seeded_db.refresh(message)
    message.processing_status = ProcessingStatus.RECEIVED
    seeded_db.commit()
    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(error="AI_TRANSIENT_FAILURE"),
    )
    seeded_db.refresh(message)
    assert result.processing_status is ProcessingStatus.FAILED
    assert message.last_processing_error_code == "AI_TRANSIENT_FAILURE"

    retried = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(analysis_result(policy="TEST-FAIL-1", client="Failure Client")),
    )
    seeded_db.refresh(message)
    assert retried.processing_status is ProcessingStatus.PROCESSED
    assert message.processing_attempt_count == 3


def test_transient_processing_failure_uses_due_time_backoff_and_then_succeeds(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db, client="Retry Client", policy="RETRY-100", subject_suffix="retry-due"
    )
    settings = Settings(
        message_process_max_auto_attempts=3,
        message_process_retry_base_seconds=30,
        message_process_retry_max_seconds=60,
    )
    first = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(error="AI_RATE_LIMITED"),
        settings=settings,
    )
    seeded_db.refresh(message)
    assert first.processing_status is ProcessingStatus.FAILED
    assert message.processing_attempt_count == 1
    assert message.processing_next_retry_at is not None
    assert claim_message(seeded_db, message_id=message.id) is None

    message.processing_next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
    seeded_db.commit()
    claimed = claim_message(seeded_db, message_id=message.id)
    assert claimed == message.id
    succeeded = process_claimed_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(analysis_result(client="Retry Client", policy="RETRY-100")),
        settings=settings,
    )
    seeded_db.refresh(message)
    assert succeeded.processing_status is ProcessingStatus.PROCESSED
    assert message.processing_attempt_count == 2
    assert message.processing_next_retry_at is None


def test_retry_exhaustion_blocks_automatic_claim_but_manual_retry_overrides(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Exhausted Client",
        policy="EXHAUSTED-100",
        subject_suffix="retry-exhausted",
    )
    settings = Settings(
        message_process_max_auto_attempts=2,
        message_process_retry_base_seconds=1,
        message_process_retry_max_seconds=1,
    )
    process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(error="AI_TIMEOUT"),
        settings=settings,
    )
    message.processing_next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
    seeded_db.commit()
    assert claim_message(seeded_db, message_id=message.id) == message.id
    process_claimed_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(error="AI_TIMEOUT"),
        settings=settings,
    )
    seeded_db.refresh(message)
    assert message.processing_attempt_count == 2
    assert message.processing_next_retry_at is None
    assert claim_message(seeded_db, message_id=message.id) is None

    connection = seeded_db.get(GmailConnection, message.gmail_connection_id)
    assert connection is not None
    current = auth_context(seeded_db, connection.user_id)
    manual = manual_process(
        seeded_db,
        current,
        message.id,
        analyzer=FakeAnalyzer(analysis_result(client="Exhausted Client", policy="EXHAUSTED-100")),
    )
    seeded_db.refresh(message)
    assert manual.processing_status is ProcessingStatus.PROCESSED
    assert message.processing_attempt_count == 3


def test_nonretryable_failure_and_stale_processing_recovery(seeded_db: Session) -> None:
    nonretryable = create_received_message(
        seeded_db,
        client="Auth Client",
        policy="AUTH-100",
        subject_suffix="auth-failure",
    )
    process_message(
        seeded_db,
        nonretryable.id,
        analyzer=FakeAnalyzer(error="AI_AUTH_FAILED"),
        settings=Settings(message_process_max_auto_attempts=3),
    )
    seeded_db.refresh(nonretryable)
    assert nonretryable.processing_next_retry_at is None

    stale = create_received_message(
        seeded_db,
        client="Stale Client",
        policy="STALE-100",
        subject_suffix="stale-processing",
    )
    stale.processing_status = ProcessingStatus.PROCESSING
    stale.processing_attempt_count = 1
    stale.processing_started_at = datetime.now(UTC) - timedelta(minutes=20)
    seeded_db.commit()
    recovered = recover_stale_processing(
        seeded_db,
        settings=Settings(
            message_process_stale_after_seconds=60,
            message_process_max_auto_attempts=3,
        ),
    )
    seeded_db.refresh(stale)
    assert recovered == 1
    assert stale.processing_status is ProcessingStatus.FAILED
    assert stale.last_processing_error_code == "STALE_PROCESSING_RECOVERED"
    assert stale.processing_next_retry_at is not None


def test_worker_isolates_one_unexpected_message_failure(test_engine, monkeypatch) -> None:
    connection = test_engine.connect()
    transaction = connection.begin()
    testing_session = sessionmaker(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        with testing_session() as db:
            from app.db.seed import seed_demo_data

            seed_demo_data(db, "worker-test-password")
            first = create_received_message(
                db, client="First Client", policy="WORKER-1", subject_suffix="worker-first"
            )
            second = create_received_message(
                db, client="Second Client", policy="WORKER-2", subject_suffix="worker-second"
            )

        called: list[int] = []

        def fake_process(db: Session, message_id: int, *, analyzer) -> ProcessingResult:
            called.append(message_id)
            if message_id == first.id:
                raise RuntimeError("synthetic unsafe detail")
            message = db.get(CarrierMessage, message_id)
            assert message is not None
            message.processing_status = ProcessingStatus.PROCESSED
            message.classification = MessageClassification.OTHER
            message.summary = "Synthetic processed message"
            message.priority = Priority.NORMAL
            db.commit()
            return ProcessingResult(message_id, ProcessingStatus.PROCESSED)

        monkeypatch.setattr("app.workers.message_process.process_claimed_message", fake_process)
        results = process_once(
            session_factory=testing_session,
            analyzer_factory=lambda: FakeAnalyzer(analysis_result()),
        )

        assert called == [first.id, second.id]
        assert [item.processing_status for item in results] == [
            ProcessingStatus.FAILED,
            ProcessingStatus.PROCESSED,
        ]
        with testing_session() as db:
            failed = db.get(CarrierMessage, first.id)
            assert failed is not None
            assert failed.last_processing_error_code == "UNEXPECTED_PROCESSING_FAILURE"
    finally:
        transaction.rollback()
        connection.close()


def test_worker_configures_windows_break_for_graceful_shutdown(monkeypatch) -> None:
    configured: list[tuple[object, object]] = []
    fake_sigbreak = object()

    monkeypatch.setattr("app.workers.message_process.signal.SIGBREAK", fake_sigbreak, raising=False)
    monkeypatch.setattr(
        "app.workers.message_process.signal.signal",
        lambda signum, handler: configured.append((signum, handler)),
    )

    _configure_shutdown_signals()

    assert configured and configured[0][0] is fake_sigbreak


def test_review_analysis_api_enforces_scope_and_applies_human_correction(
    client: TestClient, seeded_db: Session, login
) -> None:
    message = create_received_message(
        seeded_db,
        client="API Review Client",
        policy="API-REVIEW-1",
        subject_suffix="api-review",
    )
    proposed = with_interpretation_ambiguity(
        analysis_result(client="API Review Client", policy="API-REVIEW-1", confidence=0.4)
    )
    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))
    assert result.review_id is not None

    login(client, "agent.two@demo.local")
    assert client.get(f"/api/v1/reviews/{result.review_id}/analysis").status_code == 404
    assert client.get(f"/api/v1/carrier-messages/{message.id}/analysis").status_code == 404

    owner_auth = login(client, "agent.one@demo.local")
    detail = client.get(f"/api/v1/reviews/{result.review_id}/analysis")
    assert detail.status_code == 200
    assert "INTERPRETATION_AMBIGUITY" in detail.json()["analysis"]["validation_flags"]
    assert detail.json()["issues"][0]["category"] == "INTERPRETATION_AMBIGUITY"
    assert detail.json()["analysis"]["source_content"].startswith("Client: API Review Client")
    case_count = seeded_db.scalar(select(func.count()).select_from(PolicyCase))
    task_count = seeded_db.scalar(select(func.count()).select_from(Task))
    for terminal in ("RESOLVED", "DISMISSED"):
        bypass = client.patch(
            f"/api/v1/reviews/{result.review_id}",
            json={"status": terminal},
            headers={"X-CSRF-Token": owner_auth["csrf_token"]},
        )
        assert bypass.status_code == 422
    seeded_db.refresh(message)
    assert message.processing_status is ProcessingStatus.NEEDS_REVIEW
    assert message.analysis.final_result_json is None
    assert seeded_db.scalar(select(func.count()).select_from(PolicyCase)) == case_count
    assert seeded_db.scalar(select(func.count()).select_from(Task)) == task_count
    correction = proposed.model_dump(
        mode="json",
        exclude={
            "evidence",
            "source_facts",
            "interpretation_ambiguities",
            "overall_confidence",
            "uncertainties",
        },
    )
    correction["summary"] = "Human-confirmed requirements for API Review Client."
    applied = client.post(
        f"/api/v1/reviews/{result.review_id}/apply-analysis",
        json=correction,
        headers={"X-CSRF-Token": owner_auth["csrf_token"]},
    )
    assert applied.status_code == 200
    assert applied.json()["processing_status"] == "PROCESSED"
    seeded_db.refresh(message)
    assert message.analysis.final_result_json["summary"].startswith("Human-confirmed")
    assert message.analysis.model_result_json["summary"] == proposed.summary


def test_human_review_confirms_evidence_mismatch_and_materializes_once(
    client: TestClient, seeded_db: Session, login
) -> None:
    message = create_received_message(
        seeded_db,
        client="Evidence Confirmation Client",
        policy="EVIDENCE-CONFIRM-1",
        subject_suffix="evidence-confirmation",
    )
    base = analysis_result(
        client="Evidence Confirmation Client",
        policy="EVIDENCE-CONFIRM-1",
    )
    proposed = with_interpretation_ambiguity(base).model_copy(
        update={
            "evidence": [
                *base.evidence,
                Evidence(
                    field_name="summary",
                    source_id="email",
                    excerpt="This excerpt is deliberately absent from the source.",
                ),
            ]
        }
    )
    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))
    review = seeded_db.get(ReviewItem, result.review_id)
    assert review is not None and "INTERPRETATION_AMBIGUITY" in result.validation_flags
    auth = login(client, "agent.one@demo.local")
    correction = proposed.model_dump(
        mode="json",
        exclude={
            "evidence",
            "source_facts",
            "interpretation_ambiguities",
            "overall_confidence",
            "uncertainties",
        },
    )

    applied = client.post(
        f"/api/v1/reviews/{review.id}/apply-analysis",
        json=correction,
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert applied.status_code == 200
    seeded_db.refresh(message)
    seeded_db.refresh(review)
    assert message.processing_status is ProcessingStatus.PROCESSED
    assert message.processed_at is not None
    assert review.status is ReviewStatus.RESOLVED
    assert review.resolved_at is not None
    assert message.analysis.final_result_json["policy_number"] == "EVIDENCE-CONFIRM-1"
    assert all(
        item["excerpt"] != "This excerpt is deliberately absent from the source."
        for item in message.analysis.final_result_json["evidence"]
    )
    assert message.analysis.finalized_by_user_id == auth["user"]["id"]
    assert message.analysis.finalized_at is not None
    assert message.analysis.validation_flags == []
    tasks = seeded_db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()
    assert len(tasks) == 1
    case = seeded_db.get(PolicyCase, message.case_id)
    assert case is not None
    assert tasks[0].assigned_agent_id == case.assigned_agent_id
    sync = seeded_db.scalar(
        select(GmailThreadLabelSync).where(
            GmailThreadLabelSync.gmail_connection_id == message.gmail_connection_id,
            GmailThreadLabelSync.gmail_thread_id == message.gmail_thread_id,
        )
    )
    assert sync is not None and sync.status is GmailLabelSyncStatus.PENDING
    assert seeded_db.scalar(
        select(AuditEvent).where(
            AuditEvent.carrier_message_id == message.id,
            AuditEvent.event_type == "AI_REVIEW_APPLIED",
            AuditEvent.actor_user_id == auth["user"]["id"],
        )
    )

    second = client.post(
        f"/api/v1/reviews/{review.id}/apply-analysis",
        json=correction,
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert second.status_code == 409
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.source_carrier_message_id == message.id)
        )
        == 1
    )


def test_human_correction_drops_unsupported_evidence_for_changed_value(
    client: TestClient, seeded_db: Session, login
) -> None:
    message = create_received_message(
        seeded_db,
        client="Original Evidence Client",
        policy="EVIDENCE-CORRECT-1",
        subject_suffix="evidence-correction",
    )
    base = analysis_result(
        client="Original Evidence Client",
        policy="EVIDENCE-CORRECT-1",
    )
    proposed = with_interpretation_ambiguity(base).model_copy(
        update={
            "evidence": [
                *base.evidence,
                Evidence(
                    field_name="summary",
                    source_id="email",
                    excerpt="This excerpt is deliberately absent from the source.",
                ),
            ]
        }
    )
    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))
    review = seeded_db.get(ReviewItem, result.review_id)
    assert review is not None and "INTERPRETATION_AMBIGUITY" in result.validation_flags
    auth = login(client, "agent.one@demo.local")
    correction = proposed.model_dump(
        mode="json",
        exclude={
            "evidence",
            "source_facts",
            "interpretation_ambiguities",
            "overall_confidence",
            "uncertainties",
        },
    )
    correction["client_name"] = "Human Corrected Client"

    applied = client.post(
        f"/api/v1/reviews/{review.id}/apply-analysis",
        json=correction,
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert applied.status_code == 200
    seeded_db.refresh(message)
    case = seeded_db.get(PolicyCase, message.case_id)
    assert case is not None and case.client_name == "Human Corrected Client"
    assert message.analysis.final_result_json["client_name"] == "Human Corrected Client"
    assert message.analysis.finalized_by_user_id == auth["user"]["id"]
    retained_client_evidence = seeded_db.scalars(
        select(CaseEvidence).where(
            CaseEvidence.carrier_message_id == message.id,
            CaseEvidence.field_name == "client_name",
        )
    ).all()
    assert retained_client_evidence == []


def test_generic_model_uncertainty_without_competing_values_does_not_review(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Model Hesitation Client",
        policy="MODEL-HESITATION-1",
        subject_suffix="model-hesitation",
    )
    proposed = analysis_result(
        client="Model Hesitation Client",
        policy="MODEL-HESITATION-1",
    ).model_copy(update={"uncertainties": ["Synthetic ambiguity without competing values"]})

    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))

    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None


def test_consistent_source_status_corrects_model_enum_without_review(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Source Status Client",
        policy="SOURCE-STATUS-1",
        subject_suffix="source-status-grounding",
    )
    proposed = analysis_result(client="Source Status Client", policy="SOURCE-STATUS-1").model_copy(
        update={"policy_status": PolicyStatus.ACTIVE}
    )

    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))

    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None
    assert message.analysis.final_result_json["policy_status"] == "PENDING"


def test_human_review_cannot_redirect_work_to_another_agents_case(
    client: TestClient, seeded_db: Session, login
) -> None:
    message = create_received_message(
        seeded_db,
        client="Collision Source Client",
        policy="COLLISION-SOURCE-1",
        subject_suffix="cross-owner-human-collision",
    )
    proposed = with_interpretation_ambiguity(
        analysis_result(
            client="Collision Source Client",
            policy="COLLISION-SOURCE-1",
            confidence=0.4,
        )
    )
    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))
    review = seeded_db.get(ReviewItem, result.review_id)
    current_agent = seeded_db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert current_agent is not None
    other_agent = seeded_db.scalar(
        select(User).where(
            User.role == UserRole.AGENT,
            User.id != current_agent.id,
        )
    )
    assert other_agent is not None
    other_case = PolicyCase(
        agency_id=current_agent.agency_id,
        carrier_id=message.carrier_id,
        assigned_agent_id=other_agent.id,
        assignment_source=CaseAssignmentSource.MANAGER,
        client_name="Other Agent Collision Client",
        policy_number="OTHER-AGENT-COLLISION-1",
        current_policy_status=PolicyStatus.PENDING,
        priority=Priority.HIGH,
        summary="Synthetic cross-owner collision case.",
    )
    seeded_db.add(other_case)
    seeded_db.commit()
    assert review is not None and review.case_id is None and other_case is not None
    original_owner_id = other_case.assigned_agent_id
    correction = proposed.model_dump(
        mode="json",
        exclude={
            "evidence",
            "source_facts",
            "interpretation_ambiguities",
            "overall_confidence",
            "uncertainties",
        },
    )
    correction["client_name"] = other_case.client_name
    correction["policy_number"] = other_case.policy_number
    auth = login(client, "agent.one@demo.local")

    response = client.post(
        f"/api/v1/reviews/{review.id}/apply-analysis",
        json=correction,
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["issues"][0]["code"] == "CASE_OWNER_CONFLICT"
    seeded_db.refresh(other_case)
    seeded_db.refresh(review)
    assert other_case.assigned_agent_id == original_owner_id
    assert review.status is ReviewStatus.OPEN


def test_grounded_moderate_confidence_message_processes_without_review(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Grounded Confidence Client",
        policy="GROUNDED-74",
        subject_suffix="grounded-confidence",
    )

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(
            analysis_result(
                client="Grounded Confidence Client",
                policy="GROUNDED-74",
                confidence=0.4,
            ).model_copy(update={"uncertainties": []})
        ),
    )

    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None


@pytest.mark.parametrize("model_premium", ["$1,250.00 USD", "USD 1,250.00"])
def test_clean_issued_policy_human_money_format_processes_straight_through(
    seeded_db: Session, model_premium: str
) -> None:
    message = create_received_message(
        seeded_db,
        client="Emily Parker",
        policy="QA-AUTO-001",
        subject_suffix=f"qa-auto-{model_premium[:3]}",
    )
    message.cleaned_content = (
        "Client Name: Emily Parker\n"
        "Policy Number: QA-AUTO-001\n"
        "Notice Type: Policy Issued\n"
        "Policy Status: Issued\n"
        "Premium Amount: $1,250.00 USD\n"
        "Effective Date: August 28, 2026"
    )
    message.raw_content = message.cleaned_content
    seeded_db.commit()

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(
            policy_issued_result(
                client="Emily Parker",
                policy="QA-AUTO-001",
                premium=model_premium,
                currency="USD",
            )
        ),
    )

    case = seeded_db.get(PolicyCase, result.case_id)
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None
    assert case is not None and case.premium_amount == Decimal("1250.00")
    assert case.currency == "USD"
    assert message.analysis.final_result_json["premium_amount"] == "1250.00"


def test_model_currency_conflict_is_corrected_from_consistent_source(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Currency Conflict Client",
        policy="CURRENCY-CONFLICT-1",
        subject_suffix="currency-conflict",
    )
    message.cleaned_content = (
        "Client Name: Currency Conflict Client\n"
        "Policy Number: CURRENCY-CONFLICT-1\n"
        "Notice Type: Policy Issued\n"
        "Policy Status: Issued\n"
        "Premium Amount: $1,250.00 USD\n"
        "Effective Date: August 28, 2026"
    )
    message.raw_content = message.cleaned_content
    seeded_db.commit()

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(
            policy_issued_result(
                client="Currency Conflict Client",
                policy="CURRENCY-CONFLICT-1",
                premium="$1,250.00 USD",
                currency="EUR",
            )
        ),
    )

    case = seeded_db.get(PolicyCase, result.case_id)
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None
    assert case is not None and case.currency == "USD"


def test_explicit_current_status_contradiction_creates_external_task(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Olivia Thompson",
        policy="QA-CONFLICT-001",
        subject_suffix="qa-conflict",
    )
    message.cleaned_content = (
        "Client Name: Olivia Thompson\n"
        "Policy Number: QA-CONFLICT-001\n"
        "Notice Type: Policy Issued\n"
        "Policy Status: Pending\n"
        "Premium Amount: $1,250.00 USD\n"
        "Effective Date: August 28, 2026"
    )
    message.raw_content = message.cleaned_content
    seeded_db.commit()

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(
            policy_issued_result(
                client="Olivia Thompson",
                policy="QA-CONFLICT-001",
                premium="1250.00",
                currency="USD",
                status=PolicyStatus.PENDING,
            ).model_copy(
                update={"uncertainties": ["The source says issued while requiring Pending status."]}
            )
        ),
    )

    case = seeded_db.get(PolicyCase, result.case_id)
    tasks = seeded_db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None
    assert case is not None and case.current_policy_status is PolicyStatus.UNKNOWN
    assert [task.title for task in tasks] == ["Confirm current policy status with carrier"]


def test_missing_requirements_create_follow_up_task_without_review(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Missing Requirements Client",
        policy="MISSING-REQ-1",
        subject_suffix="missing-requirements",
    )
    proposed = analysis_result(
        client="Missing Requirements Client", policy="MISSING-REQ-1"
    ).model_copy(
        update={
            "requirements": [],
            "uncertainties": ["The carrier did not provide the requirements list."],
        }
    )

    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))

    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None
    titles = set(seeded_db.scalars(select(Task.title).where(Task.case_id == result.case_id)).all())
    assert "Contact carrier for outstanding requirements" in titles


def test_stored_missing_requirements_review_is_reevaluated_without_model_call(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Stored Missing Client",
        policy="STORED-MISSING-1",
        subject_suffix="stored-missing-requirements",
    )
    proposed = analysis_result(
        client="Stored Missing Client", policy="STORED-MISSING-1"
    ).model_copy(
        update={
            "requirements": [],
            "action_items": [
                ActionItem(
                    title="Contact carrier for outstanding requirements",
                    description="Ask the carrier for the omitted requirements list.",
                    priority=Priority.HIGH,
                    explicit_due_date=None,
                    due_text=None,
                )
            ],
            "evidence": [
                item
                for item in analysis_result(
                    client="Stored Missing Client", policy="STORED-MISSING-1"
                ).evidence
                if not item.field_name.startswith("action_item:")
            ],
            "uncertainties": ["The carrier did not provide the requirements list."],
        }
    )
    message.processing_status = ProcessingStatus.NEEDS_REVIEW
    connection = seeded_db.get(GmailConnection, message.gmail_connection_id)
    assert connection is not None
    analysis = MessageAnalysis(
        carrier_message_id=message.id,
        model_name="stored-test-model",
        schema_version="stage4-v1",
        prompt_version="stage4-v4",
        overall_confidence=Decimal("0.99"),
        model_result_json=proposed.model_dump(
            mode="json", exclude={"source_facts", "interpretation_ambiguities"}
        ),
        validation_flags=["MODEL_UNCERTAINTY"],
    )
    review = ReviewItem(
        agency_id=message.agency_id,
        carrier_message_id=message.id,
        assigned_reviewer_id=connection.user_id,
        status=ReviewStatus.OPEN,
        reason_code="MODEL_UNCERTAINTY",
        reason="The model reported missing requirements.",
    )
    seeded_db.add_all([analysis, review])
    seeded_db.commit()

    result = reevaluate_stored_review(seeded_db, review.id)

    seeded_db.refresh(review)
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert review.status is ReviewStatus.RESOLVED
    tasks = seeded_db.scalars(select(Task).where(Task.case_id == result.case_id)).all()
    assert [task.title for task in tasks] == ["Contact carrier for outstanding requirements"]


def test_issued_policy_missing_premium_and_effective_date_creates_tasks(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Issued Missing Client",
        policy="ISSUED-MISSING-1",
        subject_suffix="issued-missing-details",
    )
    message.cleaned_content = message.cleaned_content.replace("Status: PENDING", "Status: ISSUED")
    message.raw_content = message.cleaned_content
    seeded_db.commit()
    base = analysis_result(client="Issued Missing Client", policy="ISSUED-MISSING-1")
    proposed = base.model_copy(
        update={
            "classification": MessageClassification.POLICY_ISSUED,
            "summary": "The policy was issued without premium or effective-date details.",
            "policy_status": PolicyStatus.ISSUED,
            "deadline": Deadline(
                raw_text=None,
                explicit_date=None,
                relative_count=None,
                relative_unit=None,
            ),
            "requirements": [],
            "action_items": [],
            "evidence": [
                Evidence(
                    field_name="client_name",
                    source_id="email",
                    excerpt="Client: Issued Missing Client",
                ),
                Evidence(
                    field_name="policy_number",
                    source_id="email",
                    excerpt="Policy: ISSUED-MISSING-1",
                ),
                Evidence(
                    field_name="policy_status",
                    source_id="email",
                    excerpt="Status: ISSUED",
                ),
            ],
        }
    )

    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))

    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None
    titles = set(seeded_db.scalars(select(Task.title).where(Task.case_id == result.case_id)).all())
    assert {"Obtain premium amount from carrier", "Obtain policy effective date"} <= titles


def test_missing_policy_number_uses_one_exact_client_case_and_creates_task(
    seeded_db: Session,
) -> None:
    existing = seeded_db.scalar(
        select(PolicyCase).where(PolicyCase.policy_number == "AMR-98765432")
    )
    assert existing is not None
    owner = seeded_db.get(User, existing.assigned_agent_id)
    assert owner is not None
    message = create_received_message(
        seeded_db,
        client=existing.client_name,
        policy="OMITTED",
        subject_suffix="missing-policy-safe-match",
        owner=owner,
    )
    message.cleaned_content = message.cleaned_content.replace("Policy: OMITTED\n", "")
    message.raw_content = message.cleaned_content
    seeded_db.commit()
    proposed = analysis_result(client=existing.client_name, policy="OMITTED")
    proposed = proposed.model_copy(
        update={
            "policy_number": None,
            "evidence": [item for item in proposed.evidence if item.field_name != "policy_number"],
        }
    )

    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))

    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.case_id == existing.id
    assert result.review_id is None
    assert seeded_db.scalar(
        select(Task).where(
            Task.case_id == existing.id,
            Task.title == "Obtain policy number from carrier",
        )
    )


def test_missing_policy_number_creates_one_provisional_case_when_unambiguous(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Provisional Identity Client",
        policy="OMITTED",
        subject_suffix="provisional-missing-policy",
    )
    message.cleaned_content = message.cleaned_content.replace("Policy: OMITTED\n", "")
    message.raw_content = message.cleaned_content
    seeded_db.commit()
    proposed = analysis_result(client="Provisional Identity Client", policy="OMITTED")
    proposed = proposed.model_copy(
        update={
            "policy_number": None,
            "evidence": [item for item in proposed.evidence if item.field_name != "policy_number"],
        }
    )

    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))

    case = seeded_db.get(PolicyCase, result.case_id)
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None
    assert case is not None and case.policy_number is None
    assert seeded_db.scalar(
        select(Task).where(
            Task.case_id == case.id,
            Task.title == "Obtain policy number from carrier",
        )
    )


def test_body_pdf_policy_conflict_creates_external_verification_task(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Conflict Client",
        policy="CONFLICT-100",
        subject_suffix="source-policy-conflict",
    )
    attachment = Attachment(
        carrier_message_id=message.id,
        external_id="conflict-pdf",
        filename="policy.pdf",
        mime_type="application/pdf",
        size_bytes=128,
        processing_status=AttachmentStatus.EXTRACTED,
        extracted_text=("Client: Conflict Client\nPolicy: CONFLICT-200\nStatus: PENDING"),
        extracted_at=datetime.now(UTC),
        page_count=1,
    )
    seeded_db.add(attachment)
    seeded_db.commit()

    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(analysis_result(client="Conflict Client", policy="CONFLICT-100")),
    )

    case = seeded_db.get(PolicyCase, result.case_id)
    tasks = seeded_db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None
    assert case is not None and case.policy_number is None
    assert [task.title for task in tasks].count("Verify policy number with carrier") == 1
    verification = next(task for task in tasks if task.title == "Verify policy number with carrier")
    assert "Email body" in (verification.description or "")
    assert f"PDF attachment {attachment.id}" in (verification.description or "")


def test_natural_prose_premium_conflict_creates_one_external_task(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="John Smith",
        policy="NAT-100",
        subject_suffix="natural-premium-conflict",
    )
    email = (
        "We have issued policy NAT-100 for John Smith. "
        "The policy is issued and active. "
        "Coverage becomes effective September 5, 2026. "
        "Our issuance notice states that the current annual premium is $840. "
        "The final policy information states that the current annual premium is $920. "
        "Both figures are current and the discrepancy must be resolved."
    )
    message.cleaned_content = email
    message.raw_content = email
    seeded_db.commit()
    proposed = policy_issued_result(
        client="John Smith",
        policy="NAT-100",
        premium="840.00",
        currency="USD",
        status=PolicyStatus.ACTIVE,
    ).model_copy(
        update={
            "effective_date": "2026-09-05",
            "evidence": [
                Evidence(field_name="client_name", source_id="email", excerpt=email),
                Evidence(field_name="policy_number", source_id="email", excerpt=email),
                Evidence(
                    field_name="policy_status",
                    source_id="email",
                    excerpt="The policy is issued and active.",
                ),
                Evidence(
                    field_name="premium_amount",
                    source_id="email",
                    excerpt="the current annual premium is $840",
                ),
                Evidence(
                    field_name="effective_date",
                    source_id="email",
                    excerpt="Coverage becomes effective September 5, 2026.",
                ),
            ],
            "source_facts": [
                SourceFact(
                    field_name="premium_amount",
                    value="840.00",
                    source_id="email",
                    excerpt="the current annual premium is $840",
                ),
                SourceFact(
                    field_name="premium_amount",
                    value="920.00",
                    source_id="email",
                    excerpt="the current annual premium is $920",
                ),
            ],
        }
    )

    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))

    case = seeded_db.get(PolicyCase, result.case_id)
    tasks = seeded_db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None
    assert case is not None and case.premium_amount is None
    assert [task.title for task in tasks] == ["Resolve annual premium discrepancy with carrier"]
    assert "Obtain premium amount from carrier" not in {task.title for task in tasks}
    assert {fact["value"] for fact in message.analysis.final_result_json["source_facts"]} == {
        "840.00",
        "920.00",
    }


def test_historical_premium_is_not_a_current_discrepancy(seeded_db: Session) -> None:
    message = create_received_message(
        seeded_db,
        client="History Client",
        policy="HISTORY-100",
        subject_suffix="historical-premium",
    )
    content = (
        "We issued policy HISTORY-100 for History Client. "
        "The previous annual premium was $840, and the current annual premium is $920. "
        "The policy is issued and active. Coverage becomes effective September 5, 2026."
    )
    message.cleaned_content = content
    message.raw_content = content
    seeded_db.commit()
    proposed = policy_issued_result(
        client="History Client",
        policy="HISTORY-100",
        premium="920.00",
        currency="USD",
        status=PolicyStatus.ACTIVE,
    ).model_copy(
        update={
            "effective_date": "2026-09-05",
            "source_facts": [
                SourceFact(
                    field_name="premium_amount",
                    value="920.00",
                    source_id="email",
                    excerpt="the current annual premium is $920",
                )
            ],
        }
    )

    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))

    case = seeded_db.get(PolicyCase, result.case_id)
    tasks = seeded_db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None
    assert case is not None and case.premium_amount == Decimal("920.00")
    assert not any("discrepancy" in task.title.casefold() for task in tasks)


def test_stored_discrepancy_reconciliation_dismisses_redundant_missing_task(
    seeded_db: Session,
) -> None:
    message = create_received_message(
        seeded_db,
        client="Legacy Dispute Client",
        policy="LEGACY-DISPUTE-1",
        subject_suffix="legacy-dispute",
    )
    message.cleaned_content = (
        "Client Name: Legacy Dispute Client\n"
        "Policy Number: LEGACY-DISPUTE-1\n"
        "Notice Type: Policy Issued\n"
        "Policy Status: Issued\n"
        "Effective Date: September 5, 2026"
    )
    message.raw_content = message.cleaned_content
    seeded_db.commit()
    proposed = policy_issued_result(
        client="Legacy Dispute Client",
        policy="LEGACY-DISPUTE-1",
        premium="840.00",
        currency="USD",
    ).model_copy(
        update={
            "premium_amount": None,
            "action_items": [
                ActionItem(
                    title="Resolve annual premium discrepancy",
                    description="Reconcile the conflicting current premium amounts.",
                    priority=Priority.HIGH,
                    explicit_due_date=None,
                    due_text=None,
                )
            ],
        }
    )
    processed = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))
    assert processed.processing_status is ProcessingStatus.PROCESSED
    analysis = message.analysis
    assert analysis is not None and analysis.final_result_json is not None
    final_json = dict(analysis.final_result_json)
    final_json["action_items"] = [
        *final_json["action_items"],
        ActionItem(
            title="Obtain premium amount from carrier",
            description="Confirm the policy premium amount.",
            priority=Priority.HIGH,
            explicit_due_date=None,
            due_text=None,
        ).model_dump(mode="json"),
    ]
    analysis.final_result_json = final_json
    case = seeded_db.get(PolicyCase, processed.case_id)
    assert case is not None and case.assigned_agent_id is not None
    redundant = Task(
        agency_id=message.agency_id,
        case_id=case.id,
        source_carrier_message_id=message.id,
        source_action_index=1,
        assigned_agent_id=case.assigned_agent_id,
        title="Obtain premium amount from carrier",
        description="Confirm the policy premium amount.",
        priority=Priority.HIGH,
        status=TaskStatus.OPEN,
    )
    seeded_db.add(redundant)
    seeded_db.commit()

    dismissed = reconcile_stored_discrepancy_tasks(seeded_db, message.id)

    seeded_db.refresh(redundant)
    current_tasks = seeded_db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()
    assert dismissed == 1
    assert redundant.status is TaskStatus.DISMISSED
    assert [item["title"] for item in analysis.final_result_json["action_items"]] == [
        "Resolve annual premium discrepancy with carrier"
    ]
    assert [task.title for task in current_tasks if task.status is TaskStatus.OPEN] == [
        "Resolve annual premium discrepancy with carrier"
    ]


def test_client_spelling_dispute_uses_safe_case_and_external_task(
    seeded_db: Session,
) -> None:
    owner = seeded_db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    carrier = seeded_db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    assert owner is not None and carrier is not None
    case = PolicyCase(
        agency_id=owner.agency_id,
        carrier_id=carrier.id,
        assigned_agent_id=owner.id,
        assignment_source=CaseAssignmentSource.GMAIL,
        client_name="Sophie Bennett",
        policy_number="SPELL-100",
        current_policy_status=PolicyStatus.PENDING,
        priority=Priority.NORMAL,
        summary="Existing safely identified policy case.",
    )
    seeded_db.add(case)
    seeded_db.commit()
    message = create_received_message(
        seeded_db,
        client="Sophie Bennett",
        policy="SPELL-100",
        subject_suffix="client-spelling-dispute",
        owner=owner,
    )
    email = "We have issued the policy SPELL-100 for Sophie Bennett."
    pdf = "This policy SPELL-100 is issued to Sophie Bennet."
    message.cleaned_content = email
    message.raw_content = email
    attachment = Attachment(
        carrier_message_id=message.id,
        external_id="client-spelling-dispute-pdf",
        filename="policy.pdf",
        mime_type="application/pdf",
        size_bytes=128,
        processing_status=AttachmentStatus.EXTRACTED,
        extracted_text=pdf,
        extracted_at=datetime.now(UTC),
        page_count=1,
    )
    seeded_db.add(attachment)
    seeded_db.commit()
    proposed = analysis_result(client="Sophie Bennett", policy="SPELL-100").model_copy(
        update={
            "source_facts": [
                SourceFact(
                    field_name="client_name",
                    value="Sophie Bennett",
                    source_id="email",
                    excerpt=email,
                ),
                SourceFact(
                    field_name="client_name",
                    value="Sophie Bennet",
                    source_id=f"attachment:{attachment.id}",
                    excerpt=pdf,
                ),
            ]
        }
    )

    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))

    seeded_db.refresh(case)
    tasks = seeded_db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.review_id is None
    assert result.case_id == case.id
    assert case.client_name == "Sophie Bennett"
    assert [task.title for task in tasks].count("Verify client identity with carrier") == 1


def test_missing_policy_with_two_exact_client_cases_routes_to_case_match_review(
    seeded_db: Session,
) -> None:
    owner = seeded_db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    carrier = seeded_db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    assert owner is not None and carrier is not None
    for policy in ("DUPLICATE-CLIENT-A", "DUPLICATE-CLIENT-B"):
        seeded_db.add(
            PolicyCase(
                agency_id=owner.agency_id,
                carrier_id=carrier.id,
                assigned_agent_id=owner.id,
                assignment_source=CaseAssignmentSource.GMAIL,
                client_name="Ambiguous Client",
                policy_number=policy,
                current_policy_status=PolicyStatus.PENDING,
                priority=Priority.NORMAL,
                summary="Synthetic ambiguous identity fixture.",
            )
        )
    seeded_db.commit()
    message = create_received_message(
        seeded_db,
        client="Ambiguous Client",
        policy="OMITTED",
        subject_suffix="ambiguous-client-cases",
        owner=owner,
    )
    message.cleaned_content = message.cleaned_content.replace("Policy: OMITTED\n", "")
    message.raw_content = message.cleaned_content
    seeded_db.commit()
    proposed = analysis_result(client="Ambiguous Client", policy="OMITTED")
    proposed = proposed.model_copy(
        update={
            "policy_number": None,
            "evidence": [item for item in proposed.evidence if item.field_name != "policy_number"],
        }
    )

    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))

    assert result.processing_status is ProcessingStatus.NEEDS_REVIEW
    assert result.case_id is None
    assert "CASE_MATCH_CONFLICT" in result.validation_flags
    assert message.case_id is None


def test_missing_info_task_is_not_duplicated_by_later_message_for_same_case(
    seeded_db: Session,
) -> None:
    owner = seeded_db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert owner is not None
    first = create_received_message(
        seeded_db,
        client="Repeat Missing Client",
        policy="REPEAT-MISSING-1",
        subject_suffix="repeat-missing-first",
        owner=owner,
    )
    second = create_received_message(
        seeded_db,
        client="Repeat Missing Client",
        policy="REPEAT-MISSING-1",
        subject_suffix="repeat-missing-second",
        owner=owner,
    )
    proposed = analysis_result(
        client="Repeat Missing Client", policy="REPEAT-MISSING-1"
    ).model_copy(update={"requirements": []})

    first_result = process_message(seeded_db, first.id, analyzer=FakeAnalyzer(proposed))
    second_result = process_message(seeded_db, second.id, analyzer=FakeAnalyzer(proposed))

    assert first_result.case_id == second_result.case_id
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.case_id == first_result.case_id,
                Task.title == "Contact carrier for outstanding requirements",
            )
        )
        == 1
    )


def test_review_without_structured_proposal_can_be_dismissed(
    client: TestClient, seeded_db: Session, login
) -> None:
    message = create_received_message(
        seeded_db,
        client="Unreadable Attachment",
        policy="NO-PROPOSAL-1",
        subject_suffix="no-proposal",
    )
    add_policy_conflict_attachment(seeded_db, message, conflicting_policy="NO-PROPOSAL-2")
    result = process_message(
        seeded_db,
        message.id,
        analyzer=FakeAnalyzer(
            with_interpretation_ambiguity(
                analysis_result(
                    client="Unreadable Attachment",
                    policy="NO-PROPOSAL-1",
                    confidence=0.4,
                )
            )
        ),
    )
    assert result.review_id is not None and message.analysis is not None
    message.analysis.model_result_json = {"malformed": "synthetic regression fixture"}
    seeded_db.commit()

    auth = login(client, "agent.one@demo.local")
    detail = client.get(f"/api/v1/reviews/{result.review_id}/analysis")
    assert detail.status_code == 200
    assert detail.json()["analysis"]["proposed_result"] is None

    dismissed = client.post(
        f"/api/v1/reviews/{result.review_id}/dismiss-analysis",
        json={"resolution_notes": "Unreadable attachment; no operational record to apply."},
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["processing_status"] == "IGNORED"
    seeded_db.refresh(message)
    review = seeded_db.get(ReviewItem, result.review_id)
    assert message.processing_status is ProcessingStatus.IGNORED
    assert review is not None and review.status is ReviewStatus.DISMISSED
    assert (
        seeded_db.scalar(
            select(AuditEvent).where(
                AuditEvent.carrier_message_id == message.id,
                AuditEvent.event_type == "AI_REVIEW_DISMISSED",
            )
        )
        is not None
    )


def test_manual_processing_api_requires_csrf_and_reports_unconfigured_ai(
    client: TestClient, seeded_db: Session, login, monkeypatch
) -> None:
    message = create_received_message(
        seeded_db,
        client="Unconfigured Client",
        policy="NO-AI-1",
        subject_suffix="no-ai",
    )
    auth = login(client, "agent.one@demo.local")
    assert client.post(f"/api/v1/carrier-messages/{message.id}/process").status_code == 403
    monkeypatch.setattr(
        "app.services.message_processing.get_settings",
        lambda: SimpleNamespace(openai_configured=False),
    )
    response = client.post(
        f"/api/v1/carrier-messages/{message.id}/process",
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "AI analysis is not configured"}
