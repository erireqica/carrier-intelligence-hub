from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pymupdf
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
)
from app.models.carriers import Carrier
from app.models.enums import (
    AttachmentStatus,
    GmailConnectionStatus,
    GmailLabelSyncStatus,
    MessageClassification,
    PolicyStatus,
    Priority,
    ProcessingStatus,
    ReviewStatus,
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
    recover_stale_processing,
)
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
        uncertainties=[],
    )


def create_received_message(
    db: Session, *, client: str, policy: str, subject_suffix: str
) -> CarrierMessage:
    owner = db.scalar(select(User).where(User.role == UserRole.AGENT).order_by(User.id))
    carrier = db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    assert owner is not None and carrier is not None
    connection = GmailConnection(
        agency_id=owner.agency_id,
        user_id=owner.id,
        gmail_address=f"stage4-{subject_suffix}@gmail.test",
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


def auth_context(db: Session, user_id: int) -> AuthContext:
    user = db.get(User, user_id)
    assert user is not None
    session, _, csrf = create_session(db, user)
    db.commit()
    return AuthContext(user=user, agency=user.agency, session=session, csrf_token=csrf)


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


def test_existing_case_client_mismatch_routes_to_one_review(seeded_db: Session) -> None:
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
    assert first.processing_status is ProcessingStatus.NEEDS_REVIEW
    assert "CLIENT_MISMATCH" in first.validation_flags
    assert second.processing_status is ProcessingStatus.NEEDS_REVIEW
    assert analyzer.calls == 1
    reviews = seeded_db.scalars(
        select(ReviewItem).where(ReviewItem.carrier_message_id == message.id)
    ).all()
    assert len(reviews) == 1


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


def test_low_confidence_review_can_be_corrected_and_applied(seeded_db: Session) -> None:
    message = create_received_message(
        seeded_db, client="Review Client", policy="TEST-REVIEW-1", subject_suffix="review"
    )
    proposed = analysis_result(client="Review Client", policy="TEST-REVIEW-1", confidence=0.4)
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
    original_json = dict(message.analysis.model_result_json)
    correction = HumanAnalysisInput(
        **proposed.model_dump(exclude={"evidence", "overall_confidence", "uncertainties"})
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
    proposed = analysis_result(client="Original Client", policy="ORIGINAL-100", confidence=0.4)
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
    proposed = analysis_result(client="API Review Client", policy="API-REVIEW-1", confidence=0.4)
    result = process_message(seeded_db, message.id, analyzer=FakeAnalyzer(proposed))
    assert result.review_id is not None

    login(client, "agent.two@demo.local")
    assert client.get(f"/api/v1/reviews/{result.review_id}/analysis").status_code == 404
    assert client.get(f"/api/v1/carrier-messages/{message.id}/analysis").status_code == 404

    owner_auth = login(client, "agent.one@demo.local")
    detail = client.get(f"/api/v1/reviews/{result.review_id}/analysis")
    assert detail.status_code == 200
    assert detail.json()["analysis"]["validation_flags"] == ["LOW_CONFIDENCE"]
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
        mode="json", exclude={"evidence", "overall_confidence", "uncertainties"}
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
