from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import Settings, get_settings
from app.core.time import utc_now
from app.integrations.ai import AnalysisProviderError, AnalysisResult, Analyzer, OpenAIAnalyzer
from app.integrations.ai.prompt import ANALYSIS_PROMPT_VERSION
from app.integrations.ai.schemas import ANALYSIS_SCHEMA_VERSION, HumanAnalysisInput
from app.integrations.gmail.client import GmailMailbox, mailbox_from_credential
from app.integrations.gmail.errors import GmailReauthorizationRequired, GmailTransientError
from app.integrations.pdf import extract_pdf
from app.models.enums import (
    AttachmentStatus,
    AuditSeverity,
    MessageClassification,
    PolicyStatus,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
    UserRole,
)
from app.models.operations import (
    Attachment,
    CarrierMessage,
    CaseEvidence,
    MessageAnalysis,
    PolicyCase,
    ReviewItem,
    Task,
)
from app.models.organization import Agency, GmailConnection, GmailOAuthCredential
from app.processing.source import SourceBundle, build_source_bundle
from app.processing.validation import POLICY_CLASSIFICATIONS, ValidatedAnalysis, validate_analysis
from app.services.audit import record_audit_event
from app.services.auth import AuthContext

MailboxFactory = Callable[[GmailOAuthCredential], tuple[GmailMailbox, bool]]


@dataclass(frozen=True)
class ProcessingResult:
    message_id: int
    processing_status: ProcessingStatus
    case_id: int | None = None
    review_id: int | None = None
    tasks_created: int = 0
    attachments_extracted: int = 0
    analysis_confidence: float | None = None
    validation_flags: tuple[str, ...] = ()


REVIEW_REASONS = {
    "LOW_CONFIDENCE": "The model confidence signal is below the automatic threshold.",
    "MISSING_POLICY_NUMBER": "A reliable policy number was not found.",
    "MISSING_CLIENT_NAME": "A reliable client name was not found.",
    "UNKNOWN_POLICY_STATUS": "The policy status could not be determined.",
    "CLASSIFICATION_STATUS_MISMATCH": "The communication type conflicts with its policy status.",
    "EVIDENCE_MISMATCH": "One or more proposed facts are not supported by verified source text.",
    "PDF_NEEDS_OCR": "A PDF contains little or no extractable text and needs manual review.",
    "PDF_EXTRACTION_FAILED": "A PDF could not be extracted safely.",
    "SOURCE_TRUNCATED": "The source exceeded the configured analysis limit.",
    "SOURCE_INCOMPLETE": "The available email and attachment text is incomplete.",
    "CLIENT_MISMATCH": "The extracted client conflicts with the existing policy case.",
    "INVALID_PREMIUM": "The proposed premium or currency is invalid.",
    "INVALID_DATE": "A proposed date is invalid.",
    "INVALID_DEADLINE": "The proposed deadline is invalid.",
    "MODEL_UNCERTAINTY": "The model identified unresolved ambiguity.",
    "ACTION_WITHOUT_CASE": "Actionable work could not be linked to a reliable policy case.",
    "AI_INVALID_RESPONSE": "The structured model response could not be validated.",
    "AI_REFUSAL": "The model did not return a usable structured analysis.",
}


def _load_message(db: Session, message_id: int) -> CarrierMessage | None:
    return db.scalar(
        select(CarrierMessage)
        .where(CarrierMessage.id == message_id)
        .options(
            joinedload(CarrierMessage.carrier),
            joinedload(CarrierMessage.case),
            joinedload(CarrierMessage.analysis),
            selectinload(CarrierMessage.attachments),
        )
    )


def _connection(db: Session, message: CarrierMessage) -> GmailConnection | None:
    if message.gmail_connection_id is None:
        return None
    return db.scalar(
        select(GmailConnection)
        .where(GmailConnection.id == message.gmail_connection_id)
        .options(joinedload(GmailConnection.oauth_credential))
    )


def claim_message(
    db: Session,
    *,
    message_id: int | None = None,
    allow_failed: bool = False,
) -> int | None:
    statuses = [ProcessingStatus.RECEIVED]
    if allow_failed:
        statuses.append(ProcessingStatus.FAILED)
    query = (
        select(CarrierMessage)
        .where(CarrierMessage.processing_status.in_(statuses))
        .order_by(CarrierMessage.received_at, CarrierMessage.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if message_id is not None:
        query = query.where(CarrierMessage.id == message_id)
    message = db.scalar(query)
    if message is None:
        db.rollback()
        return None
    message.processing_status = ProcessingStatus.PROCESSING
    message.processing_attempt_count += 1
    message.processing_started_at = utc_now()
    message.processed_at = None
    message.last_processing_error_code = None
    record_audit_event(
        db,
        agency_id=message.agency_id,
        carrier_message_id=message.id,
        event_type="MESSAGE_PROCESSING_STARTED",
        description="Carrier message processing started",
        metadata={"attempt": message.processing_attempt_count},
    )
    db.commit()
    return message.id


def mark_failed(db: Session, message_id: int, code: str) -> ProcessingResult:
    db.rollback()
    message = db.get(CarrierMessage, message_id)
    if message is None:
        raise LookupError("Carrier message not found")
    message.processing_status = ProcessingStatus.FAILED
    message.last_processing_error_code = code
    message.processing_started_at = None
    record_audit_event(
        db,
        agency_id=message.agency_id,
        carrier_message_id=message.id,
        event_type="AI_ANALYSIS_FAILED",
        severity=AuditSeverity.ERROR,
        description="Carrier message processing failed",
        metadata={"error_code": code},
    )
    db.commit()
    return ProcessingResult(message.id, ProcessingStatus.FAILED)


def _persist_attachment_result(
    db: Session,
    attachment_id: int,
    *,
    status_value: AttachmentStatus,
    text_value: str | None,
    page_count: int | None,
    error_code: str | None,
) -> None:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        return
    attachment.processing_status = status_value
    attachment.extracted_text = text_value
    attachment.page_count = page_count
    attachment.extraction_error_code = error_code
    attachment.extracted_at = utc_now() if status_value is AttachmentStatus.EXTRACTED else None
    if status_value is AttachmentStatus.EXTRACTED:
        message = db.get(CarrierMessage, attachment.carrier_message_id)
        assert message is not None
        record_audit_event(
            db,
            agency_id=message.agency_id,
            carrier_message_id=message.id,
            event_type="PDF_EXTRACTED",
            description="PDF attachment text extracted",
            metadata={"attachment_id": attachment.id, "page_count": page_count},
        )
    db.commit()


def _process_attachments(
    db: Session,
    message_id: int,
    *,
    settings: Settings,
    mailbox_factory: MailboxFactory,
) -> tuple[int, set[str]]:
    message = _load_message(db, message_id)
    assert message is not None
    pending = [
        item for item in message.attachments if item.processing_status is AttachmentStatus.PENDING
    ]
    connection = _connection(db, message)
    db.commit()
    mailbox: GmailMailbox | None = None
    extracted = 0
    flags: set[str] = set()
    for item in pending:
        if item.mime_type.lower() != "application/pdf":
            _persist_attachment_result(
                db,
                item.id,
                status_value=AttachmentStatus.UNSUPPORTED,
                text_value=None,
                page_count=None,
                error_code="ATTACHMENT_UNSUPPORTED",
            )
            continue
        if item.size_bytes > settings.pdf_max_attachment_bytes:
            _persist_attachment_result(
                db,
                item.id,
                status_value=AttachmentStatus.FAILED,
                text_value=None,
                page_count=None,
                error_code="PDF_TOO_LARGE",
            )
            flags.add("PDF_EXTRACTION_FAILED")
            continue
        if (
            item.external_id is None
            or message.gmail_message_id is None
            or connection is None
            or connection.oauth_credential is None
        ):
            raise GmailTransientError("Gmail attachment data was unavailable.")
        if mailbox is None:
            mailbox, refreshed = mailbox_factory(connection.oauth_credential)
            if refreshed:
                db.commit()
        content = mailbox.get_attachment(message.gmail_message_id, item.external_id)
        result = extract_pdf(
            content,
            mime_type=item.mime_type,
            max_bytes=settings.pdf_max_attachment_bytes,
            max_pages=settings.pdf_max_pages,
        )
        _persist_attachment_result(
            db,
            item.id,
            status_value=result.status,
            text_value=result.text,
            page_count=result.page_count,
            error_code=result.error_code,
        )
        if result.status is AttachmentStatus.EXTRACTED:
            extracted += 1
        elif result.status is AttachmentStatus.NEEDS_OCR:
            flags.add("PDF_NEEDS_OCR")
        elif result.status is AttachmentStatus.FAILED:
            flags.add("PDF_EXTRACTION_FAILED")
    return extracted, flags


def _case_for_result(
    db: Session, message: CarrierMessage, result: AnalysisResult
) -> PolicyCase | None:
    if not result.policy_number:
        return None
    return db.scalar(
        select(PolicyCase).where(
            PolicyCase.agency_id == message.agency_id,
            PolicyCase.carrier_id == message.carrier_id,
            func.upper(PolicyCase.policy_number) == result.policy_number.upper(),
        )
    )


def _client_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _upsert_analysis(
    db: Session,
    message: CarrierMessage,
    result: AnalysisResult,
    validated: ValidatedAnalysis,
    model_name: str,
) -> MessageAnalysis:
    analysis = message.analysis
    if analysis is None:
        analysis = MessageAnalysis()
        message.analysis = analysis
    analysis.model_name = model_name
    analysis.schema_version = ANALYSIS_SCHEMA_VERSION
    analysis.prompt_version = ANALYSIS_PROMPT_VERSION
    analysis.overall_confidence = Decimal(str(result.overall_confidence))
    analysis.model_result_json = result.model_dump(mode="json")
    analysis.validation_flags = list(validated.flags)
    return analysis


def _review_for_flags(
    db: Session,
    message: CarrierMessage,
    flags: tuple[str, ...],
    *,
    existing_case: PolicyCase | None,
    model_name: str,
    confidence: float | None,
) -> ReviewItem:
    primary = flags[0] if flags else "AI_INVALID_RESPONSE"
    review = db.scalar(
        select(ReviewItem).where(
            ReviewItem.carrier_message_id == message.id,
            ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
        )
    )
    connection = _connection(db, message)
    reviewer_id = (
        existing_case.assigned_agent_id
        if existing_case and existing_case.assigned_agent_id
        else connection.user_id
        if connection
        else None
    )
    if review is None:
        review = ReviewItem(
            agency_id=message.agency_id,
            case_id=existing_case.id if existing_case else None,
            carrier_message_id=message.id,
            assigned_reviewer_id=reviewer_id,
            status=ReviewStatus.OPEN,
            reason_code=primary,
            reason=REVIEW_REASONS.get(primary, "The analysis requires human review."),
        )
        db.add(review)
    else:
        review.reason_code = primary
        review.reason = REVIEW_REASONS.get(primary, "The analysis requires human review.")
    message.processing_status = ProcessingStatus.NEEDS_REVIEW
    message.processing_started_at = None
    message.last_processing_error_code = None
    record_audit_event(
        db,
        agency_id=message.agency_id,
        case_id=existing_case.id if existing_case else None,
        carrier_message_id=message.id,
        event_type="AI_REVIEW_REQUIRED",
        severity=AuditSeverity.WARNING,
        description="Carrier message requires human review",
        metadata={
            "validation_flags": list(flags),
            "model_name": model_name,
            "confidence": confidence,
        },
    )
    db.commit()
    db.refresh(review)
    return review


def _action_due_at(
    action_date: str | None, fallback: datetime | None, timezone_name: str
) -> datetime | None:
    if not action_date:
        return fallback
    due_date = date.fromisoformat(action_date)
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = UTC
    return datetime.combine(due_date, time(17, 0), timezone).astimezone(UTC)


def _finalize(
    db: Session,
    message: CarrierMessage,
    analysis: MessageAnalysis,
    validated: ValidatedAnalysis,
    bundle: SourceBundle,
    *,
    actor_user_id: int | None,
    review: ReviewItem | None = None,
) -> ProcessingResult:
    result = validated.result
    agency = db.get(Agency, message.agency_id)
    assert agency is not None
    case = _case_for_result(db, message, result)
    created = False
    if result.classification in POLICY_CLASSIFICATIONS:
        assert result.client_name and result.policy_number
        if case is None:
            connection = _connection(db, message)
            if connection is None:
                raise RuntimeError("Message connection unavailable")
            case = PolicyCase(
                agency_id=message.agency_id,
                carrier_id=message.carrier_id,
                assigned_agent_id=connection.user_id,
                client_name=result.client_name,
                policy_number=result.policy_number,
                current_policy_status=result.policy_status,
                priority=result.priority,
                summary=result.summary,
            )
            db.add(case)
            db.flush()
            created = True
        case.summary = result.summary
        case.priority = result.priority
        if result.policy_status is not PolicyStatus.UNKNOWN:
            case.current_policy_status = result.policy_status
        if validated.premium_amount is not None:
            case.premium_amount = validated.premium_amount
        if result.currency is not None:
            case.currency = result.currency
        if validated.effective_date is not None:
            case.effective_date = validated.effective_date
        if validated.deadline_at is not None:
            case.current_deadline = validated.deadline_at
        elif (
            result.classification is MessageClassification.POLICY_ISSUED
            and result.policy_status
            in {
                PolicyStatus.ISSUED,
                PolicyStatus.ACTIVE,
            }
        ):
            case.current_deadline = None

    message.case_id = case.id if case else None
    message.classification = result.classification
    message.summary = result.summary
    message.priority = result.priority
    message.original_deadline_text = result.deadline.raw_text

    tasks_created = 0
    if case is not None:
        connection = _connection(db, message)
        assigned_agent_id = case.assigned_agent_id or (
            connection.user_id if connection is not None else None
        )
        if assigned_agent_id is None:
            raise RuntimeError("No task assignee is available")
        for index, action in enumerate(result.action_items):
            task = db.scalar(
                select(Task).where(
                    Task.source_carrier_message_id == message.id,
                    Task.source_action_index == index,
                )
            )
            if task is None:
                task = Task(
                    agency_id=message.agency_id,
                    case_id=case.id,
                    source_carrier_message_id=message.id,
                    source_action_index=index,
                    assigned_agent_id=assigned_agent_id,
                    status=TaskStatus.OPEN,
                    title=action.title,
                    description=action.description,
                    priority=action.priority,
                    due_at=_action_due_at(
                        action.explicit_due_date, validated.deadline_at, agency.timezone
                    ),
                )
                db.add(task)
                tasks_created += 1

        existing_evidence = db.scalars(
            select(CaseEvidence).where(CaseEvidence.carrier_message_id == message.id)
        ).all()
        for evidence in existing_evidence:
            db.delete(evidence)
        for evidence in validated.verified_evidence:
            db.add(
                CaseEvidence(
                    case_id=case.id,
                    carrier_message_id=message.id,
                    attachment_id=evidence.attachment_id,
                    field_name=evidence.proposal.field_name,
                    source_type=evidence.source_type,
                    excerpt=evidence.proposal.excerpt,
                    created_at=utc_now(),
                )
            )

    analysis.final_result_json = result.model_dump(mode="json")
    analysis.finalized_by_user_id = actor_user_id
    analysis.finalized_at = utc_now()
    analysis.validation_flags = []
    message.processing_status = ProcessingStatus.PROCESSED
    message.processing_started_at = None
    message.processed_at = utc_now()
    message.last_processing_error_code = None
    if review is not None:
        review.case_id = case.id if case else None
        review.status = ReviewStatus.RESOLVED
        review.resolved_at = utc_now()
    record_audit_event(
        db,
        agency_id=message.agency_id,
        actor_user_id=actor_user_id,
        case_id=case.id if case else None,
        carrier_message_id=message.id,
        event_type=("CASE_CREATED_FROM_MESSAGE" if created else "CASE_UPDATED_FROM_MESSAGE"),
        description=(
            "Policy case created from carrier message"
            if created
            else "Carrier message analysis applied"
        ),
    )
    if tasks_created:
        record_audit_event(
            db,
            agency_id=message.agency_id,
            actor_user_id=actor_user_id,
            case_id=case.id if case else None,
            carrier_message_id=message.id,
            event_type="AI_TASKS_CREATED",
            description="Source-linked tasks created from carrier message",
            metadata={"task_count": tasks_created},
        )
    if actor_user_id is not None:
        record_audit_event(
            db,
            agency_id=message.agency_id,
            actor_user_id=actor_user_id,
            case_id=case.id if case else None,
            carrier_message_id=message.id,
            event_type="AI_REVIEW_APPLIED",
            description="Human-reviewed analysis applied",
        )
    db.commit()
    return ProcessingResult(
        message_id=message.id,
        processing_status=ProcessingStatus.PROCESSED,
        case_id=case.id if case else None,
        tasks_created=tasks_created,
        analysis_confidence=float(analysis.overall_confidence),
    )


def process_claimed_message(
    db: Session,
    message_id: int,
    *,
    analyzer: Analyzer,
    settings: Settings | None = None,
    mailbox_factory: MailboxFactory = mailbox_from_credential,
) -> ProcessingResult:
    active = settings or get_settings()
    try:
        attachments_extracted, source_flags = _process_attachments(
            db,
            message_id,
            settings=active,
            mailbox_factory=mailbox_factory,
        )
    except GmailReauthorizationRequired, GmailTransientError:
        return mark_failed(db, message_id, "ATTACHMENT_DOWNLOAD_FAILED")
    except Exception:
        return mark_failed(db, message_id, "PDF_EXTRACTION_FAILED")

    message = _load_message(db, message_id)
    if message is None:
        raise LookupError("Carrier message not found")
    bundle = build_source_bundle(message, max_chars=active.ai_max_source_chars)
    if bundle.truncated:
        source_flags.add("SOURCE_TRUNCATED")
    if not message.cleaned_content.strip() and not any(
        document.source_type == "PDF" for document in bundle.documents
    ):
        source_flags.add("SOURCE_INCOMPLETE")
    db.commit()
    try:
        result = analyzer.analyze(bundle.rendered)
    except AnalysisProviderError as error:
        if not error.reviewable:
            return mark_failed(db, message_id, error.code)
        message = _load_message(db, message_id)
        assert message is not None
        review = _review_for_flags(
            db,
            message,
            (error.code,),
            existing_case=message.case,
            model_name=analyzer.model_name,
            confidence=None,
        )
        return ProcessingResult(
            message.id,
            ProcessingStatus.NEEDS_REVIEW,
            case_id=message.case_id,
            review_id=review.id,
            attachments_extracted=attachments_extracted,
            validation_flags=(error.code,),
        )

    message = _load_message(db, message_id)
    assert message is not None
    agency = db.get(Agency, message.agency_id)
    assert agency is not None
    validated = validate_analysis(
        result,
        bundle,
        agency_timezone=agency.timezone,
        confidence_threshold=active.ai_auto_apply_confidence_threshold,
        source_flags=source_flags,
    )
    flags = set(validated.flags)
    case = _case_for_result(db, message, validated.result)
    if (
        case
        and validated.result.client_name
        and _client_key(case.client_name) != _client_key(validated.result.client_name)
    ):
        flags.add("CLIENT_MISMATCH")
    if (
        case is None
        and validated.result.classification not in POLICY_CLASSIFICATIONS
        and validated.result.action_items
    ):
        flags.add("ACTION_WITHOUT_CASE")
    if flags != set(validated.flags):
        validated = ValidatedAnalysis(
            result=validated.result,
            flags=tuple(sorted(flags)),
            verified_evidence=validated.verified_evidence,
            premium_amount=validated.premium_amount,
            effective_date=validated.effective_date,
            deadline_at=validated.deadline_at,
        )
    analysis = _upsert_analysis(db, message, result, validated, analyzer.model_name)
    record_audit_event(
        db,
        agency_id=message.agency_id,
        carrier_message_id=message.id,
        event_type="AI_ANALYSIS_COMPLETED",
        description="Structured carrier message analysis completed",
        metadata={
            "model_name": analyzer.model_name,
            "confidence": result.overall_confidence,
            "validation_flags": list(validated.flags),
        },
    )
    if not validated.safe_to_apply:
        review = _review_for_flags(
            db,
            message,
            validated.flags,
            existing_case=case,
            model_name=analyzer.model_name,
            confidence=result.overall_confidence,
        )
        return ProcessingResult(
            message.id,
            ProcessingStatus.NEEDS_REVIEW,
            case_id=case.id if case else None,
            review_id=review.id,
            attachments_extracted=attachments_extracted,
            analysis_confidence=result.overall_confidence,
            validation_flags=validated.flags,
        )
    try:
        finalized = _finalize(db, message, analysis, validated, bundle, actor_user_id=None)
    except Exception:
        return mark_failed(db, message_id, "MATERIALIZATION_FAILED")
    return ProcessingResult(
        **{
            **finalized.__dict__,
            "attachments_extracted": attachments_extracted,
        }
    )


def process_message(
    db: Session,
    message_id: int,
    *,
    analyzer: Analyzer | None = None,
    settings: Settings | None = None,
    mailbox_factory: MailboxFactory = mailbox_from_credential,
) -> ProcessingResult:
    active = settings or get_settings()
    selected = analyzer or OpenAIAnalyzer(active)
    claimed = claim_message(db, message_id=message_id, allow_failed=True)
    if claimed is None:
        message = _load_message(db, message_id)
        if message is None:
            raise LookupError("Carrier message not found")
        analysis = message.analysis
        return ProcessingResult(
            message.id,
            message.processing_status,
            case_id=message.case_id,
            analysis_confidence=(
                float(analysis.overall_confidence) if analysis is not None else None
            ),
            validation_flags=(tuple(analysis.validation_flags) if analysis is not None else ()),
        )
    return process_claimed_message(
        db,
        claimed,
        analyzer=selected,
        settings=active,
        mailbox_factory=mailbox_factory,
    )


def authorize_message(db: Session, current: AuthContext, message_id: int) -> CarrierMessage:
    message = _load_message(db, message_id)
    if message is None or message.agency_id != current.user.agency_id:
        raise HTTPException(status_code=404, detail="Carrier message not found")
    if current.user.role is UserRole.AGENT:
        connection = _connection(db, message)
        owns_connection = connection is not None and connection.user_id == current.user.id
        owns_case = message.case is not None and message.case.assigned_agent_id == current.user.id
        if not owns_connection and not owns_case:
            raise HTTPException(status_code=404, detail="Carrier message not found")
    return message


def manual_process(
    db: Session,
    current: AuthContext,
    message_id: int,
    *,
    analyzer: Analyzer | None = None,
) -> ProcessingResult:
    message = authorize_message(db, current, message_id)
    if message.processing_status is ProcessingStatus.PROCESSING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Analysis is in progress")
    if message.processing_status is ProcessingStatus.NEEDS_REVIEW:
        raise HTTPException(status_code=409, detail="This message requires human review")
    if message.processing_status is ProcessingStatus.IGNORED:
        raise HTTPException(status_code=409, detail="This message was dismissed")
    if analyzer is None and not get_settings().openai_configured:
        raise HTTPException(status_code=503, detail="AI analysis is not configured")
    return process_message(db, message_id, analyzer=analyzer)


def apply_review(
    db: Session,
    current: AuthContext,
    review_id: int,
    correction: HumanAnalysisInput,
) -> ProcessingResult:
    from app.services.operations import get_review_item

    get_review_item(db, current, review_id)
    review = db.get(ReviewItem, review_id)
    assert review is not None
    if review.status in {ReviewStatus.RESOLVED, ReviewStatus.DISMISSED}:
        raise HTTPException(status_code=409, detail="This review is already finalized")
    message = _load_message(db, review.carrier_message_id)
    assert message is not None
    bundle = build_source_bundle(message, max_chars=get_settings().ai_max_source_chars)
    original = message.analysis
    evidence = []
    confidence = 0.0
    model_name = get_settings().openai_model
    if original is not None:
        confidence = float(original.overall_confidence)
        model_name = original.model_name
        try:
            evidence = AnalysisResult.model_validate(original.model_result_json).evidence
        except ValueError:
            evidence = []
    result = AnalysisResult(
        **correction.model_dump(),
        evidence=evidence,
        overall_confidence=confidence,
        uncertainties=[],
    )
    agency = db.get(Agency, message.agency_id)
    assert agency is not None
    validated = validate_analysis(
        result,
        bundle,
        agency_timezone=agency.timezone,
        confidence_threshold=0,
        require_evidence=False,
    )
    blocking = set(validated.flags) - {"MODEL_UNCERTAINTY", "LOW_CONFIDENCE"}
    case = _case_for_result(db, message, validated.result)
    if (
        case
        and validated.result.client_name
        and _client_key(case.client_name) != _client_key(validated.result.client_name)
    ):
        blocking.add("CLIENT_MISMATCH")
    if blocking:
        raise HTTPException(
            status_code=422,
            detail=f"Correct the remaining validation issue: {sorted(blocking)[0]}",
        )
    if original is None:
        original = MessageAnalysis(
            carrier_message_id=message.id,
            model_name=model_name,
            schema_version=ANALYSIS_SCHEMA_VERSION,
            prompt_version=ANALYSIS_PROMPT_VERSION,
            overall_confidence=Decimal("0"),
            model_result_json={},
            validation_flags=[],
        )
        db.add(original)
    return _finalize(
        db,
        message,
        original,
        validated,
        bundle,
        actor_user_id=current.user.id,
        review=review,
    )


def dismiss_review(
    db: Session, current: AuthContext, review_id: int, notes: str | None
) -> ProcessingResult:
    from app.services.operations import get_review_item

    get_review_item(db, current, review_id)
    review = db.get(ReviewItem, review_id)
    assert review is not None
    if review.status in {ReviewStatus.RESOLVED, ReviewStatus.DISMISSED}:
        raise HTTPException(status_code=409, detail="This review is already finalized")
    message = db.get(CarrierMessage, review.carrier_message_id)
    assert message is not None
    review.status = ReviewStatus.DISMISSED
    review.resolution_notes = notes
    review.resolved_at = utc_now()
    message.processing_status = ProcessingStatus.IGNORED
    message.processing_started_at = None
    record_audit_event(
        db,
        agency_id=message.agency_id,
        actor_user_id=current.user.id,
        case_id=message.case_id,
        carrier_message_id=message.id,
        event_type="AI_REVIEW_DISMISSED",
        description="Carrier message review dismissed as non-operational",
    )
    db.commit()
    return ProcessingResult(message.id, ProcessingStatus.IGNORED, case_id=message.case_id)
