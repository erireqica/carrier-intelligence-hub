from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import Settings, get_settings
from app.core.time import utc_now
from app.integrations.ai import AnalysisProviderError, AnalysisResult, Analyzer, OpenAIAnalyzer
from app.integrations.ai.prompt import ANALYSIS_PROMPT_VERSION
from app.integrations.ai.schemas import (
    ANALYSIS_SCHEMA_VERSION,
    ActionItem,
    HumanAnalysisInput,
)
from app.integrations.gmail.client import GmailMailbox, mailbox_from_credential
from app.integrations.gmail.errors import GmailReauthorizationRequired, GmailTransientError
from app.integrations.pdf import extract_pdf
from app.models.audit import AuditEvent
from app.models.enums import (
    AttachmentStatus,
    AuditSeverity,
    CaseAssignmentSource,
    GmailConnectionStatus,
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
    MessageAnalysis,
    PolicyCase,
    ReviewItem,
    Task,
)
from app.models.organization import Agency, GmailConnection, GmailOAuthCredential, User
from app.processing.ambiguities import verify_interpretation_ambiguities
from app.processing.conflicts import SourceConflict, detect_source_conflicts, unique_source_values
from app.processing.source import SourceBundle, build_source_bundle
from app.processing.validation import (
    POLICY_CLASSIFICATIONS,
    ValidatedAnalysis,
    evidence_supports_proposed_value,
    normalize_analysis_result,
    post_human_review_blocking_flags,
    validate_analysis,
)
from app.services.audit import record_audit_event
from app.services.auth import AuthContext
from app.services.gmail_labels import enqueue_for_message
from app.services.processing_failures import RETRYABLE_PROCESSING_CODES

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


@dataclass(frozen=True)
class OperationalOwnershipReconciliation:
    previous_assignee_id: int | None
    active_tasks_reassigned: int
    active_reviews_reassigned: int
    source_messages_linked: int
    ownership_conflicts_reconciled: int


class CompletedCaseReplayBlocked(RuntimeError):
    """Prevent an old physical message from recreating active work on a closed Case."""


REVIEW_REASONS = {
    "LOW_CONFIDENCE": "The model confidence signal is below the automatic threshold.",
    "MISSING_POLICY_NUMBER": "A reliable policy number was not found.",
    "MISSING_CLIENT_NAME": "A reliable client name was not found.",
    "UNKNOWN_POLICY_STATUS": "The policy status could not be determined.",
    "CLASSIFICATION_STATUS_MISMATCH": "The communication type conflicts with its policy status.",
    "EVIDENCE_MISMATCH": "One or more proposed facts are not supported by verified source text.",
    "EVIDENCE_INCOMPLETE": "Some proposed facts do not include verifiable source evidence.",
    "PDF_NEEDS_OCR": "A PDF contains little or no extractable text and needs manual review.",
    "PDF_EXTRACTION_FAILED": "A PDF could not be extracted safely.",
    "SOURCE_TRUNCATED": "The source exceeded the configured analysis limit.",
    "SOURCE_INCOMPLETE": "The available email and attachment text is incomplete.",
    "CLIENT_MISMATCH": "The extracted client conflicts with the existing policy case.",
    "CASE_OWNER_CONFLICT": (
        "This policy is currently owned through a different Gmail inbox and requires "
        "a safe ownership decision."
    ),
    "OPERATIONAL_OWNER_REQUIRED": (
        "This communication cannot create operational work until an active agent owns the case."
    ),
    "INVALID_PREMIUM": "The proposed premium or currency is invalid.",
    "INVALID_DATE": "A proposed date is invalid.",
    "INVALID_DEADLINE": "The proposed deadline is invalid.",
    "MODEL_UNCERTAINTY": "The model identified unresolved ambiguity.",
    "ACTION_WITHOUT_CASE": "Actionable work could not be linked to a reliable policy case.",
    "AI_INVALID_RESPONSE": "The structured model response could not be validated.",
    "AI_REFUSAL": "The model did not return a usable structured analysis.",
    "POLICY_NUMBER_CONFLICT": "The carrier sources contain different policy numbers.",
    "CLIENT_IDENTITY_CONFLICT": "The carrier sources identify different clients.",
    "PREMIUM_CONFLICT": "The carrier sources contain different premium amounts.",
    "CURRENCY_CONFLICT": "The carrier sources contain different premium currencies.",
    "POLICY_STATUS_CONFLICT": "The carrier sources contain incompatible policy statuses.",
    "EFFECTIVE_DATE_CONFLICT": "The carrier sources contain different effective dates.",
    "CASE_MATCH_CONFLICT": "The incoming message matches more than one existing case.",
    "INTERPRETATION_AMBIGUITY": (
        "The available source supports more than one plausible interpretation."
    ),
}

MISSING_INFO_TASK_TITLES = frozenset(
    {
        "Obtain premium amount from carrier",
        "Obtain policy effective date",
        "Request policy document from carrier",
        "Contact carrier for outstanding requirements",
        "Obtain policy number from carrier",
        "Obtain client name from carrier",
        "Confirm current policy status with carrier",
        "Resolve annual premium discrepancy with carrier",
        "Resolve premium currency discrepancy with carrier",
        "Verify client identity with carrier",
        "Confirm policy effective date with carrier",
        "Verify policy number with carrier",
    }
)

VALIDATION_FIELDS = {
    "INVALID_PREMIUM": "premium_amount",
    "CURRENCY_CONFLICT": "currency",
    "INVALID_DATE": "effective_date",
    "INVALID_DEADLINE": "deadline",
    "CLIENT_MISMATCH": "client_name",
    "POLICY_NUMBER_CONFLICT": "policy_number",
    "CLIENT_IDENTITY_CONFLICT": "client_name",
    "PREMIUM_CONFLICT": "premium_amount",
    "POLICY_STATUS_CONFLICT": "policy_status",
    "EFFECTIVE_DATE_CONFLICT": "effective_date",
}

GENERIC_MACHINE_SIGNALS = frozenset(
    {
        "LOW_CONFIDENCE",
        "MODEL_UNCERTAINTY",
        "EVIDENCE_INCOMPLETE",
        "EVIDENCE_MISMATCH",
    }
)


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
        .options(joinedload(GmailConnection.oauth_credential), joinedload(GmailConnection.owner))
    )


def _active_agent_id(db: Session, user_id: int | None) -> int | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or user.role is not UserRole.AGENT or not user.is_active:
        return None
    return user.id


def _connection_agent_id(db: Session, message: CarrierMessage) -> int | None:
    connection = _connection(db, message)
    if connection is None or connection.status is GmailConnectionStatus.DISCONNECTED:
        return None
    return _active_agent_id(db, connection.user_id)


def _case_has_operational_agent(db: Session, case: PolicyCase | None) -> bool:
    return case is not None and _active_agent_id(db, case.assigned_agent_id) is not None


def claim_message(
    db: Session,
    *,
    message_id: int | None = None,
    allow_failed: bool = False,
) -> int | None:
    now = utc_now()
    eligibility = (
        CarrierMessage.processing_status.in_([ProcessingStatus.RECEIVED, ProcessingStatus.FAILED])
        if allow_failed
        else or_(
            CarrierMessage.processing_status == ProcessingStatus.RECEIVED,
            and_(
                CarrierMessage.processing_status == ProcessingStatus.FAILED,
                CarrierMessage.processing_next_retry_at.is_not(None),
                CarrierMessage.processing_next_retry_at <= now,
            ),
        )
    )
    query = (
        select(CarrierMessage)
        .where(eligibility)
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
    message.processing_started_at = now
    message.processing_next_retry_at = None
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
    enqueue_for_message(db, message)
    db.commit()
    return message.id


def _processing_backoff(settings: Settings, attempt: int) -> timedelta:
    seconds = min(
        settings.message_process_retry_base_seconds * (2 ** max(attempt - 1, 0)),
        settings.message_process_retry_max_seconds,
    )
    return timedelta(seconds=seconds)


def mark_failed(
    db: Session,
    message_id: int,
    code: str,
    *,
    settings: Settings | None = None,
) -> ProcessingResult:
    active = settings or get_settings()
    db.rollback()
    message = db.get(CarrierMessage, message_id)
    if message is None:
        raise LookupError("Carrier message not found")
    message.processing_status = ProcessingStatus.FAILED
    message.last_processing_error_code = code
    message.processing_started_at = None
    retryable = code in RETRYABLE_PROCESSING_CODES
    retry_scheduled = retryable and (
        message.processing_attempt_count < active.message_process_max_auto_attempts
    )
    message.processing_next_retry_at = (
        utc_now() + _processing_backoff(active, message.processing_attempt_count)
        if retry_scheduled
        else None
    )
    enqueue_for_message(db, message)
    record_audit_event(
        db,
        agency_id=message.agency_id,
        carrier_message_id=message.id,
        event_type="AI_ANALYSIS_FAILED",
        severity=AuditSeverity.ERROR,
        description="Carrier message processing failed",
        metadata={"error_code": code},
    )
    if retry_scheduled:
        record_audit_event(
            db,
            agency_id=message.agency_id,
            carrier_message_id=message.id,
            event_type="PROCESSING_RETRY_SCHEDULED",
            severity=AuditSeverity.WARNING,
            description="Automatic carrier message retry scheduled",
            metadata={
                "attempt": message.processing_attempt_count,
                "error_code": code,
                "next_retry_at": message.processing_next_retry_at.isoformat(),
            },
        )
    elif retryable:
        record_audit_event(
            db,
            agency_id=message.agency_id,
            carrier_message_id=message.id,
            event_type="PROCESSING_RETRY_EXHAUSTED",
            severity=AuditSeverity.ERROR,
            description="Automatic carrier message retries exhausted",
            metadata={"attempt": message.processing_attempt_count, "error_code": code},
        )
    db.commit()
    return ProcessingResult(message.id, ProcessingStatus.FAILED)


def mark_gmail_reauth_required(db: Session, message_id: int) -> ProcessingResult:
    db.rollback()
    message = db.get(CarrierMessage, message_id)
    if message is None:
        raise LookupError("Carrier message not found")
    message.processing_status = ProcessingStatus.FAILED
    message.last_processing_error_code = "GMAIL_REAUTH_REQUIRED"
    message.processing_started_at = None
    message.processing_next_retry_at = None
    connection = _connection(db, message)
    if connection is not None:
        connection.status = GmailConnectionStatus.NEEDS_REAUTH
        connection.last_error_summary = (
            "Google authorization is no longer valid. Reconnect this inbox."
        )
    enqueue_for_message(db, message)
    record_audit_event(
        db,
        agency_id=message.agency_id,
        carrier_message_id=message.id,
        event_type="GMAIL_REAUTH_REQUIRED",
        severity=AuditSeverity.WARNING,
        description="Gmail authorization must be renewed before processing can continue",
        metadata={
            "connection_id": message.gmail_connection_id,
            "error_code": "GMAIL_REAUTH_REQUIRED",
        },
    )
    db.commit()
    return ProcessingResult(message.id, ProcessingStatus.FAILED)


def recover_stale_processing(db: Session, *, settings: Settings | None = None) -> int:
    active = settings or get_settings()
    now = utc_now()
    cutoff = now - timedelta(seconds=active.message_process_stale_after_seconds)
    messages = db.scalars(
        select(CarrierMessage)
        .where(
            CarrierMessage.processing_status == ProcessingStatus.PROCESSING,
            CarrierMessage.processing_started_at < cutoff,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for message in messages:
        message.processing_status = ProcessingStatus.FAILED
        message.processing_started_at = None
        message.last_processing_error_code = "STALE_PROCESSING_RECOVERED"
        message.processing_next_retry_at = (
            now
            if message.processing_attempt_count < active.message_process_max_auto_attempts
            else None
        )
        enqueue_for_message(db, message)
        record_audit_event(
            db,
            agency_id=message.agency_id,
            carrier_message_id=message.id,
            event_type="STALE_PROCESSING_RECOVERED",
            severity=AuditSeverity.WARNING,
            description="Stale carrier message processing lease recovered",
            metadata={"attempt": message.processing_attempt_count},
        )
        record_audit_event(
            db,
            agency_id=message.agency_id,
            carrier_message_id=message.id,
            event_type=(
                "PROCESSING_RETRY_SCHEDULED"
                if message.processing_next_retry_at is not None
                else "PROCESSING_RETRY_EXHAUSTED"
            ),
            severity=AuditSeverity.WARNING,
            description=(
                "Automatic carrier message retry scheduled"
                if message.processing_next_retry_at is not None
                else "Automatic carrier message retries exhausted"
            ),
            metadata={
                "attempt": message.processing_attempt_count,
                "error_code": "STALE_PROCESSING_RECOVERED",
            },
        )
    db.commit()
    return len(messages)


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


def _case_candidates(
    db: Session, message: CarrierMessage, result: AnalysisResult
) -> list[PolicyCase]:
    query = select(PolicyCase).where(
        PolicyCase.agency_id == message.agency_id,
        PolicyCase.carrier_id == message.carrier_id,
    )
    if result.policy_number:
        query = query.where(func.upper(PolicyCase.policy_number) == result.policy_number.upper())
    elif result.client_name:
        query = query.where(
            func.lower(func.trim(PolicyCase.client_name)) == _client_key(result.client_name)
        )
    else:
        return []
    return list(db.scalars(query.limit(3)).all())


def _case_for_result(
    db: Session, message: CarrierMessage, result: AnalysisResult
) -> PolicyCase | None:
    candidates = _case_candidates(db, message, result)
    return candidates[0] if len(candidates) == 1 else None


def _missing_information_actions(
    validated: ValidatedAnalysis,
    disputed_fields: set[str] | frozenset[str] = frozenset(),
) -> tuple[ValidatedAnalysis, set[str]]:
    result = validated.result
    disputed_fields = set(disputed_fields) | _disputed_fields_from_actions(result.action_items)
    result = _without_redundant_missing_actions(result, disputed_fields)
    task_titles: list[tuple[str, str]] = []
    flags = set(validated.flags)
    missing_flags = {
        "MISSING_POLICY_NUMBER",
        "MISSING_CLIENT_NAME",
        "UNKNOWN_POLICY_STATUS",
        "PDF_NEEDS_OCR",
        "PDF_EXTRACTION_FAILED",
    }
    if "MISSING_POLICY_NUMBER" in flags and "policy_number" not in disputed_fields:
        task_titles.append(
            ("Obtain policy number from carrier", "Request the missing policy number.")
        )
    if "MISSING_CLIENT_NAME" in flags and "client_name" not in disputed_fields:
        task_titles.append(("Obtain client name from carrier", "Confirm the insured's name."))
    if "UNKNOWN_POLICY_STATUS" in flags and "policy_status" not in disputed_fields:
        task_titles.append(
            ("Confirm current policy status with carrier", "Obtain the current policy status.")
        )
    if flags & {"PDF_NEEDS_OCR", "PDF_EXTRACTION_FAILED"}:
        task_titles.append(
            (
                "Request policy document from carrier",
                "Obtain a readable copy of the referenced policy document.",
            )
        )
    if result.classification is MessageClassification.POLICY_ISSUED:
        if result.premium_amount is None and "premium_amount" not in disputed_fields:
            task_titles.append(
                ("Obtain premium amount from carrier", "Confirm the policy premium amount.")
            )
        if result.effective_date is None and "effective_date" not in disputed_fields:
            task_titles.append(
                ("Obtain policy effective date", "Confirm the policy effective date.")
            )
    if (
        result.classification is MessageClassification.PENDING_REQUIREMENTS
        and not result.requirements
    ):
        task_titles.append(
            (
                "Contact carrier for outstanding requirements",
                "Ask the carrier to identify the outstanding underwriting requirements.",
            )
        )
    existing = {action.title.casefold() for action in result.action_items}
    additions = [
        ActionItem(
            title=title,
            description=description,
            priority=Priority.HIGH,
            explicit_due_date=None,
            due_text=None,
        )
        for title, description in task_titles
        if title.casefold() not in existing
    ]
    flags.difference_update(missing_flags)
    return (
        ValidatedAnalysis(
            result=result.model_copy(update={"action_items": [*result.action_items, *additions]}),
            flags=tuple(sorted(flags)),
            verified_evidence=validated.verified_evidence,
            premium_amount=validated.premium_amount,
            effective_date=validated.effective_date,
            deadline_at=validated.deadline_at,
        ),
        missing_flags & set(validated.flags),
    )


_DISCREPANCY_TASKS = {
    "premium_amount": (
        "Resolve annual premium discrepancy with carrier",
        "The carrier communication reports competing current annual premiums: {values}. "
        "Confirm the correct amount with the carrier.",
    ),
    "currency": (
        "Resolve premium currency discrepancy with carrier",
        "The carrier communication reports competing premium currencies: {values}. "
        "Confirm the correct currency with the carrier.",
    ),
    "policy_status": (
        "Confirm current policy status with carrier",
        "The carrier communication reports competing current policy statuses: {values}. "
        "Confirm the authoritative status with the carrier.",
    ),
    "client_name": (
        "Verify client identity with carrier",
        "The carrier communication identifies the client differently: {values}. "
        "Verify the correct client identity with the carrier.",
    ),
    "effective_date": (
        "Confirm policy effective date with carrier",
        "The carrier communication reports competing effective dates: {values}. "
        "Confirm the correct date with the carrier.",
    ),
    "policy_number": (
        "Verify policy number with carrier",
        "The carrier communication reports competing policy numbers: {values}. "
        "Verify the correct policy number with the carrier.",
    ),
}

_REDUNDANT_MISSING_TASKS = {
    "premium_amount": "Obtain premium amount from carrier",
    "effective_date": "Obtain policy effective date",
    "policy_number": "Obtain policy number from carrier",
    "client_name": "Obtain client name from carrier",
}


def _operational_conflict_field(conflict: SourceConflict) -> str:
    return "policy_status" if conflict.field_name == "classification" else conflict.field_name


def _conflict_values(conflict: SourceConflict, result: AnalysisResult) -> str:
    values: list[str] = []
    for item in conflict.values:
        value = item.value
        if (
            conflict.field_name == "premium_amount"
            and result.currency
            and not any(marker in value.upper() for marker in (result.currency, "$"))
        ):
            value = f"{result.currency} {value}"
        rendered = f"{item.source_label} — {value}"
        if rendered.casefold() not in {existing.casefold() for existing in values}:
            values.append(rendered)
    return "; ".join(values[:4])


def _action_resolves_field(action: ActionItem, field_name: str) -> bool:
    text = f"{action.title} {action.description or ''}".casefold()
    keywords = {
        "premium_amount": ("premium",),
        "currency": ("currency",),
        "policy_status": ("policy status", "current status"),
        "client_name": ("client identity", "client name"),
        "effective_date": ("effective date",),
        "policy_number": ("policy number",),
    }[field_name]
    resolution_terms = ("discrep", "conflict", "reconcile", "verify", "confirm")
    return any(keyword in text for keyword in keywords) and any(
        term in text for term in resolution_terms
    )


def _action_declares_discrepancy(action: ActionItem, field_name: str) -> bool:
    text = f"{action.title} {action.description or ''}".casefold()
    keywords = {
        "premium_amount": ("premium",),
        "currency": ("currency",),
        "policy_status": ("policy status", "current status"),
        "client_name": ("client identity", "client name"),
        "effective_date": ("effective date",),
        "policy_number": ("policy number",),
    }[field_name]
    return any(keyword in text for keyword in keywords) and any(
        term in text for term in ("discrep", "conflict", "reconcile")
    )


def _disputed_fields_from_actions(actions: list[ActionItem]) -> set[str]:
    return {
        field_name
        for field_name in _DISCREPANCY_TASKS
        if any(_action_declares_discrepancy(action, field_name) for action in actions)
    }


def _without_redundant_missing_actions(
    result: AnalysisResult, disputed_fields: set[str] | frozenset[str]
) -> AnalysisResult:
    actions = [
        action
        for action in result.action_items
        if not any(
            field_name in disputed_fields and action.title == title
            for field_name, title in _REDUNDANT_MISSING_TASKS.items()
        )
    ]
    return result.model_copy(update={"action_items": actions})


def _apply_external_discrepancies(
    result: AnalysisResult, conflicts: tuple[SourceConflict, ...]
) -> tuple[AnalysisResult, frozenset[str]]:
    disputed_fields = {
        field_name
        for conflict in conflicts
        if (field_name := _operational_conflict_field(conflict)) in _DISCREPANCY_TASKS
    }
    if not disputed_fields:
        return result, frozenset()

    actions = list(result.action_items)
    handled_fields: set[str] = set()
    for conflict in conflicts:
        field_name = _operational_conflict_field(conflict)
        if field_name not in disputed_fields or field_name in handled_fields:
            continue
        handled_fields.add(field_name)
        title, description_template = _DISCREPANCY_TASKS[field_name]
        action = ActionItem(
            title=title,
            description=description_template.format(values=_conflict_values(conflict, result)),
            priority=Priority.HIGH,
            explicit_due_date=None,
            due_text=None,
        )
        matching_index = next(
            (
                index
                for index, existing in enumerate(actions)
                if _action_resolves_field(existing, field_name)
            ),
            None,
        )
        if matching_index is None:
            actions.append(action)
        else:
            actions[matching_index] = action

    updates: dict[str, object] = {"action_items": actions}
    for field_name in disputed_fields:
        if field_name == "policy_status":
            updates[field_name] = PolicyStatus.UNKNOWN
        else:
            updates[field_name] = None
    return result.model_copy(update=updates), frozenset(disputed_fields)


def _apply_case_identity_discrepancy(validated: ValidatedAnalysis) -> ValidatedAnalysis:
    result = validated.result
    action = ActionItem(
        title=_DISCREPANCY_TASKS["client_name"][0],
        description=(
            "The carrier communication identifies a different client than the safely matched "
            "policy case. Verify the correct client identity with the carrier."
        ),
        priority=Priority.HIGH,
        explicit_due_date=None,
        due_text=None,
    )
    actions = list(result.action_items)
    matching_index = next(
        (
            index
            for index, existing in enumerate(actions)
            if _action_resolves_field(existing, "client_name")
        ),
        None,
    )
    if matching_index is None:
        actions.append(action)
    else:
        actions[matching_index] = action
    flags = set(validated.flags)
    flags.discard("CLIENT_MISMATCH")
    return ValidatedAnalysis(
        result=result.model_copy(update={"client_name": None, "action_items": actions}),
        flags=tuple(sorted(flags)),
        verified_evidence=validated.verified_evidence,
        premium_amount=validated.premium_amount,
        effective_date=validated.effective_date,
        deadline_at=validated.deadline_at,
    )


def _drop_incomplete_evidence_when_source_is_deterministic(
    validated: ValidatedAnalysis, bundle: SourceBundle
) -> ValidatedAnalysis:
    if "EVIDENCE_INCOMPLETE" not in validated.flags:
        return validated
    result = validated.result
    evidenced = {item.proposal.field_name for item in validated.verified_evidence}
    deterministic = set(unique_source_values(bundle, result.source_facts))
    critical = {
        field_name
        for field_name, value in {
            "client_name": result.client_name,
            "policy_number": result.policy_number,
            "policy_status": (
                result.policy_status if result.policy_status is not PolicyStatus.UNKNOWN else None
            ),
            "premium_amount": result.premium_amount,
            "effective_date": result.effective_date,
            "deadline": result.deadline.raw_text,
        }.items()
        if value is not None
    }
    actions_grounded = all(
        f"action_item:{index}" in evidenced for index in range(len(result.action_items))
    )
    if not actions_grounded or not all(
        field_name in evidenced or field_name in deterministic for field_name in critical
    ):
        return validated
    flags = set(validated.flags)
    flags.discard("EVIDENCE_INCOMPLETE")
    return ValidatedAnalysis(
        result=validated.result,
        flags=tuple(sorted(flags)),
        verified_evidence=validated.verified_evidence,
        premium_amount=validated.premium_amount,
        effective_date=validated.effective_date,
        deadline_at=validated.deadline_at,
    )


def _apply_semantic_routing_policy(
    validated: ValidatedAnalysis,
) -> ValidatedAnalysis:
    """Keep Review flags tied to a concrete choice or hard operational invariant."""
    flags = set(validated.flags)
    flags.difference_update(GENERIC_MACHINE_SIGNALS)
    if "CLASSIFICATION_STATUS_MISMATCH" in flags and "POLICY_STATUS_CONFLICT" not in flags:
        flags.discard("CLASSIFICATION_STATUS_MISMATCH")
    return ValidatedAnalysis(
        result=validated.result,
        flags=tuple(sorted(flags)),
        verified_evidence=validated.verified_evidence,
        premium_amount=validated.premium_amount,
        effective_date=validated.effective_date,
        deadline_at=validated.deadline_at,
    )


def _ground_result_from_consistent_sources(
    result: AnalysisResult, bundle: SourceBundle
) -> AnalysisResult:
    values = unique_source_values(bundle, result.source_facts)
    updates: dict[str, object] = {}
    for field_name in (
        "client_name",
        "policy_number",
        "premium_amount",
        "currency",
        "effective_date",
    ):
        if field_name in values:
            updates[field_name] = values[field_name]
    if "policy_status" in values:
        updates["policy_status"] = PolicyStatus(values["policy_status"])
    if "classification" in values:
        updates["classification"] = MessageClassification(values["classification"])
    return result.model_copy(update=updates) if updates else result


def _reconcile_case_owner(
    db: Session,
    message: CarrierMessage,
    case: PolicyCase | None,
) -> bool:
    """Keep Case ownership authoritative, except for a proven same-mailbox handoff."""
    if case is None or case.assigned_agent_id is None:
        return False
    if not _case_has_operational_agent(db, case):
        return False
    connection = _connection(db, message)
    if connection is None or connection.status is GmailConnectionStatus.DISCONNECTED:
        return False
    if case.assignment_source is CaseAssignmentSource.MANAGER:
        reconcile_case_operational_ownership(
            db,
            case,
            assigned_agent_id=case.assigned_agent_id,
            assignment_source=case.assignment_source,
            actor_user_id=None,
        )
        return False
    if case.assigned_agent_id == connection.user_id:
        reconcile_case_operational_ownership(
            db,
            case,
            assigned_agent_id=case.assigned_agent_id,
            assignment_source=case.assignment_source,
            actor_user_id=None,
        )
        return False
    if _active_agent_id(db, connection.user_id) is None:
        return False

    former_owner_id = case.assigned_agent_id
    historical_connection_id = db.scalar(
        select(GmailConnection.id)
        .join(
            CarrierMessage,
            CarrierMessage.gmail_connection_id == GmailConnection.id,
        )
        .where(
            CarrierMessage.case_id == case.id,
            GmailConnection.agency_id == message.agency_id,
            GmailConnection.user_id == former_owner_id,
            GmailConnection.status == GmailConnectionStatus.DISCONNECTED,
            func.lower(GmailConnection.gmail_address)
            == connection.gmail_address.strip().casefold(),
        )
        .limit(1)
    )
    if historical_connection_id is None:
        reconcile_case_operational_ownership(
            db,
            case,
            assigned_agent_id=case.assigned_agent_id,
            assignment_source=case.assignment_source,
            actor_user_id=None,
        )
        return False

    ownership = reconcile_case_operational_ownership(
        db,
        case,
        assigned_agent_id=connection.user_id,
        assignment_source=CaseAssignmentSource.GMAIL_HANDOFF,
        actor_user_id=None,
    )
    record_audit_event(
        db,
        agency_id=message.agency_id,
        case_id=case.id,
        carrier_message_id=message.id,
        event_type="CASE_OWNERSHIP_TRANSFERRED",
        description="Case ownership transferred after a verified same-mailbox handoff",
        metadata={
            "former_owner_id": former_owner_id,
            "new_owner_id": connection.user_id,
            "active_tasks_transferred": ownership.active_tasks_reassigned,
            "active_reviews_transferred": ownership.active_reviews_reassigned,
            "source_messages_linked": ownership.source_messages_linked,
            "ownership_conflicts_reconciled": ownership.ownership_conflicts_reconciled,
        },
    )
    return False


def _client_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _message_was_materialized(db: Session, message: CarrierMessage) -> bool:
    return (
        db.scalar(
            select(AuditEvent.id)
            .where(
                AuditEvent.carrier_message_id == message.id,
                AuditEvent.event_type.in_(
                    ["CASE_CREATED_FROM_MESSAGE", "CASE_UPDATED_FROM_MESSAGE"]
                ),
            )
            .limit(1)
        )
        is not None
    )


def _reactivate_for_new_operational_work(
    db: Session, case: PolicyCase, message: CarrierMessage
) -> bool:
    """Reopen only for a physical message that has never been materialized before."""
    if case.completed_at is None:
        return True
    if _message_was_materialized(db, message):
        return False
    previous_completed_at = case.completed_at
    previous_completed_by_user_id = case.completed_by_user_id
    case.completed_at = None
    case.completed_by_user_id = None
    record_audit_event(
        db,
        agency_id=case.agency_id,
        case_id=case.id,
        carrier_message_id=message.id,
        event_type="CASE_REOPENED",
        description="Carrier Hub reopened the case for new carrier work",
        metadata={
            "trigger": "NEW_CARRIER_COMMUNICATION",
            "previous_completed_at": previous_completed_at.isoformat(),
            "previous_completed_by_user_id": previous_completed_by_user_id,
        },
    )
    return True


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
    if existing_case is not None:
        locked_case = db.scalar(
            select(PolicyCase).where(PolicyCase.id == existing_case.id).with_for_update()
        )
        assert locked_case is not None
        existing_case = locked_case
        if existing_case.completed_at is not None and not _reactivate_for_new_operational_work(
            db, existing_case, message
        ):
            raise CompletedCaseReplayBlocked
    primary = flags[0] if flags else "AI_INVALID_RESPONSE"
    review = db.scalar(
        select(ReviewItem).where(
            ReviewItem.carrier_message_id == message.id,
            ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
        )
    )
    connection = _connection(db, message)
    reviewer_id = (
        _active_agent_id(db, existing_case.assigned_agent_id)
        if existing_case is not None
        else _active_agent_id(db, connection.user_id)
        if connection is not None
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
        review.case_id = existing_case.id if existing_case else None
        review.assigned_reviewer_id = reviewer_id
        review.reason_code = primary
        review.reason = REVIEW_REASONS.get(primary, "The analysis requires human review.")
    if existing_case is not None:
        message.case_id = existing_case.id
    message.processing_status = ProcessingStatus.NEEDS_REVIEW
    message.processing_started_at = None
    message.processing_next_retry_at = None
    message.last_processing_error_code = None
    enqueue_for_message(db, message)
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
    case_override: PolicyCase | None = None,
) -> ProcessingResult:
    result = validated.result
    agency = db.get(Agency, message.agency_id)
    assert agency is not None
    case = case_override or _case_for_result(db, message, result)
    if case is not None and (
        case.agency_id != message.agency_id or case.carrier_id != message.carrier_id
    ):
        raise RuntimeError("Case association does not match the source message")
    completed_replay = False
    if case is not None:
        locked_case = db.scalar(
            select(PolicyCase).where(PolicyCase.id == case.id).with_for_update()
        )
        assert locked_case is not None
        case = locked_case
        if case.completed_at is not None and result.action_items:
            completed_replay = not _reactivate_for_new_operational_work(db, case, message)
    created = False
    if result.classification in POLICY_CLASSIFICATIONS:
        if case is None:
            if not result.client_name:
                raise RuntimeError("Insufficient identity to create a policy case")
            connection = _connection(db, message)
            if connection is None:
                raise RuntimeError("Message connection unavailable")
            assigned_agent_id = _active_agent_id(db, connection.user_id)
            if assigned_agent_id is None:
                raise RuntimeError("No active agent is available for the case")
            case = PolicyCase(
                agency_id=message.agency_id,
                carrier_id=message.carrier_id,
                assigned_agent_id=assigned_agent_id,
                assignment_source=CaseAssignmentSource.GMAIL,
                client_name=result.client_name,
                policy_number=result.policy_number,
                current_policy_status=result.policy_status,
                priority=result.priority,
                summary=result.summary,
            )
            db.add(case)
            db.flush()
            created = True
        elif case_override is not None:
            case.client_name = result.client_name
            case.policy_number = result.policy_number
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
        assigned_agent_id = _active_agent_id(db, case.assigned_agent_id)
        if assigned_agent_id is None:
            raise RuntimeError("No task assignee is available")
        source_tasks = db.scalars(
            select(Task).where(Task.source_carrier_message_id == message.id)
        ).all()
        source_tasks_by_index = {
            task.source_action_index: task
            for task in source_tasks
            if task.source_action_index is not None
        }
        current_action_indexes: set[int] = set()
        for index, action in enumerate(result.action_items):
            current_action_indexes.add(index)
            task = source_tasks_by_index.get(index)
            if task is None and action.title in MISSING_INFO_TASK_TITLES:
                task = db.scalar(
                    select(Task).where(
                        Task.case_id == case.id,
                        Task.source_carrier_message_id.is_not(None),
                        Task.title == action.title,
                        Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
                    )
                )
            if task is None:
                if completed_replay:
                    continue
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
            elif task.status in {TaskStatus.OPEN, TaskStatus.IN_PROGRESS}:
                task.case_id = case.id
                task.assigned_agent_id = assigned_agent_id
                task.title = action.title
                task.description = action.description
                task.priority = action.priority
                task.due_at = _action_due_at(
                    action.explicit_due_date, validated.deadline_at, agency.timezone
                )

        stale_tasks = [
            task
            for task in source_tasks
            if task.source_action_index not in current_action_indexes
            and task.status in {TaskStatus.OPEN, TaskStatus.IN_PROGRESS}
        ]
        for task in stale_tasks:
            task.status = TaskStatus.DISMISSED
        if stale_tasks:
            record_audit_event(
                db,
                agency_id=message.agency_id,
                actor_user_id=actor_user_id,
                case_id=case.id,
                carrier_message_id=message.id,
                event_type="STALE_SOURCE_TASKS_DISMISSED",
                description="Stale source-linked tasks were dismissed during reconciliation",
                metadata={"task_ids": [task.id for task in stale_tasks]},
            )

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
    message.processing_next_retry_at = None
    message.processed_at = utc_now()
    message.last_processing_error_code = None
    if review is not None:
        review.case_id = case.id if case else None
        review.status = ReviewStatus.RESOLVED
        review.resolved_at = utc_now()
    enqueue_for_message(db, message)
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


def _ownership_conflict_matches_case(review: ReviewItem, case: PolicyCase) -> bool:
    if review.case_id == case.id:
        return True
    if review.case_id is not None or review.carrier_message.case_id is not None:
        return False
    message = review.carrier_message
    analysis = message.analysis
    if (
        message.agency_id != case.agency_id
        or message.carrier_id != case.carrier_id
        or analysis is None
        or not case.policy_number
    ):
        return False
    try:
        result = AnalysisResult.model_validate(analysis.model_result_json)
    except ValueError:
        return False
    return bool(
        result.policy_number
        and result.policy_number.strip().casefold() == case.policy_number.strip().casefold()
    )


def reconcile_case_owner_conflicts(
    db: Session,
    case: PolicyCase,
    *,
    actor_user_id: int | None,
) -> int:
    """Resolve active ownership blockers from stored analysis without another LLM call."""
    reviews = db.scalars(
        select(ReviewItem)
        .where(
            ReviewItem.agency_id == case.agency_id,
            ReviewItem.reason_code == "CASE_OWNER_CONFLICT",
            ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
        )
        .options(
            joinedload(ReviewItem.carrier_message).joinedload(CarrierMessage.analysis),
            joinedload(ReviewItem.carrier_message).joinedload(CarrierMessage.carrier),
            joinedload(ReviewItem.carrier_message).selectinload(CarrierMessage.attachments),
        )
    ).all()
    agency = db.get(Agency, case.agency_id)
    assert agency is not None
    reconciled = 0
    for review in reviews:
        if not _ownership_conflict_matches_case(review, case):
            continue
        message = review.carrier_message
        analysis = message.analysis
        if analysis is None:
            continue
        try:
            result = AnalysisResult.model_validate(analysis.model_result_json)
        except ValueError:
            continue

        message.case_id = case.id
        review.case_id = case.id
        review.assigned_reviewer_id = case.assigned_agent_id
        bundle = build_source_bundle(message, max_chars=get_settings().ai_max_source_chars)
        retained_flags = set(analysis.validation_flags) - {"CASE_OWNER_CONFLICT"}
        result = _ground_result_from_consistent_sources(result, bundle)
        conflicts = detect_source_conflicts(bundle, result.source_facts)
        result, disputed_fields = _apply_external_discrepancies(result, conflicts)
        validated = validate_analysis(
            result,
            bundle,
            agency_timezone=agency.timezone,
            confidence_threshold=get_settings().ai_auto_apply_confidence_threshold,
            source_flags=retained_flags,
        )
        validated = _drop_incomplete_evidence_when_source_is_deterministic(validated, bundle)
        validated, _missing_flags = _missing_information_actions(validated, disputed_fields)
        if validated.result.client_name and _client_key(case.client_name) != _client_key(
            validated.result.client_name
        ):
            validated = _apply_case_identity_discrepancy(validated)
        flags = set(validated.flags)
        if verify_interpretation_ambiguities(bundle, result.interpretation_ambiguities):
            flags.add("INTERPRETATION_AMBIGUITY")
        if flags != set(validated.flags):
            validated = ValidatedAnalysis(
                result=validated.result,
                flags=tuple(sorted(flags)),
                verified_evidence=validated.verified_evidence,
                premium_amount=validated.premium_amount,
                effective_date=validated.effective_date,
                deadline_at=validated.deadline_at,
            )
        validated = _apply_semantic_routing_policy(validated)
        validated = _retain_only_verified_human_evidence(validated)
        analysis.validation_flags = list(validated.flags)
        if validated.safe_to_apply:
            _finalize(
                db,
                message,
                analysis,
                validated,
                bundle,
                actor_user_id=actor_user_id,
                review=review,
            )
        else:
            _review_for_flags(
                db,
                message,
                validated.flags,
                existing_case=case,
                model_name=analysis.model_name,
                confidence=float(analysis.overall_confidence),
            )
        reconciled += 1
    return reconciled


def reconcile_legacy_case_owner_reviews(
    db: Session,
    *,
    agency_id: int,
    actor_user_id: int | None,
) -> int:
    """Re-evaluate only legacy mailbox-owner conflict reviews from stored analysis."""
    cases = db.scalars(
        select(PolicyCase)
        .where(
            PolicyCase.agency_id == agency_id,
            PolicyCase.assigned_agent_id.is_not(None),
        )
        .order_by(PolicyCase.id)
    ).all()
    reconciled = sum(
        reconcile_case_owner_conflicts(db, case, actor_user_id=actor_user_id) for case in cases
    )
    if reconciled:
        record_audit_event(
            db,
            agency_id=agency_id,
            actor_user_id=actor_user_id,
            event_type="CASE_OWNER_CONFLICTS_RECONCILED",
            description="Legacy mailbox-owner conflict reviews were safely re-evaluated",
            metadata={"reviews_reconciled": reconciled},
        )
        db.commit()
    return reconciled


def reconcile_case_operational_ownership(
    db: Session,
    case: PolicyCase,
    *,
    assigned_agent_id: int,
    assignment_source: CaseAssignmentSource,
    actor_user_id: int | None,
) -> OperationalOwnershipReconciliation:
    """Move all active Case work together and repair safely recoverable associations."""
    previous_assignee_id = case.assigned_agent_id
    active_tasks = db.scalars(
        select(Task).where(
            Task.case_id == case.id,
            Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
        )
    ).all()
    active_reviews = db.scalars(
        select(ReviewItem)
        .where(
            ReviewItem.case_id == case.id,
            ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
        )
        .options(joinedload(ReviewItem.carrier_message))
    ).all()

    case.assigned_agent_id = assigned_agent_id
    case.assignment_source = assignment_source
    tasks_reassigned = 0
    reviews_reassigned = 0
    messages_linked = 0
    for task in active_tasks:
        if task.assigned_agent_id != assigned_agent_id:
            task.assigned_agent_id = assigned_agent_id
            tasks_reassigned += 1
    for review in active_reviews:
        if review.assigned_reviewer_id != assigned_agent_id:
            review.assigned_reviewer_id = assigned_agent_id
            reviews_reassigned += 1
        message = review.carrier_message
        if (
            message.case_id is None
            and message.agency_id == case.agency_id
            and message.carrier_id == case.carrier_id
        ):
            message.case_id = case.id
            messages_linked += 1

    ownership_conflicts = reconcile_case_owner_conflicts(
        db,
        case,
        actor_user_id=actor_user_id,
    )
    return OperationalOwnershipReconciliation(
        previous_assignee_id=previous_assignee_id,
        active_tasks_reassigned=tasks_reassigned,
        active_reviews_reassigned=reviews_reassigned,
        source_messages_linked=messages_linked,
        ownership_conflicts_reconciled=ownership_conflicts,
    )


def _prepare_analysis_routing(
    db: Session,
    message: CarrierMessage,
    result: AnalysisResult,
    bundle: SourceBundle,
    *,
    confidence_threshold: float,
    source_flags: set[str] | None = None,
) -> tuple[ValidatedAnalysis, PolicyCase | None]:
    agency = db.get(Agency, message.agency_id)
    assert agency is not None
    normalized = normalize_analysis_result(result)
    grounded = _ground_result_from_consistent_sources(normalized, bundle)
    conflicts = detect_source_conflicts(bundle, grounded.source_facts)
    grounded, disputed_fields = _apply_external_discrepancies(grounded, conflicts)
    validated = validate_analysis(
        grounded,
        bundle,
        agency_timezone=agency.timezone,
        confidence_threshold=confidence_threshold,
        source_flags=source_flags,
    )
    validated = _drop_incomplete_evidence_when_source_is_deterministic(validated, bundle)
    validated, _missing_flags = _missing_information_actions(validated, disputed_fields)
    flags = set(validated.flags)
    if verify_interpretation_ambiguities(bundle, grounded.interpretation_ambiguities):
        flags.add("INTERPRETATION_AMBIGUITY")
    candidates = _case_candidates(db, message, validated.result)
    if len(candidates) > 1:
        flags.add("CASE_MATCH_CONFLICT")
    case = candidates[0] if len(candidates) == 1 else None
    owner_conflict = _reconcile_case_owner(db, message, case)
    if owner_conflict:
        flags.add("CASE_OWNER_CONFLICT")
    elif validated.result.classification in POLICY_CLASSIFICATIONS and (
        (case is not None and not _case_has_operational_agent(db, case))
        or (case is None and _connection_agent_id(db, message) is None)
    ):
        flags.add("OPERATIONAL_OWNER_REQUIRED")
    if (
        case
        and validated.result.client_name
        and _client_key(case.client_name) != _client_key(validated.result.client_name)
    ):
        validated = _apply_case_identity_discrepancy(validated)
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
    return (
        _retain_only_verified_human_evidence(_apply_semantic_routing_policy(validated)),
        case,
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
    except GmailReauthorizationRequired:
        return mark_gmail_reauth_required(db, message_id)
    except GmailTransientError:
        return mark_failed(db, message_id, "ATTACHMENT_DOWNLOAD_FAILED", settings=active)
    except Exception:
        return mark_failed(db, message_id, "PDF_EXTRACTION_FAILED", settings=active)

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
            return mark_failed(db, message_id, error.code, settings=active)
        message = _load_message(db, message_id)
        assert message is not None
        try:
            review = _review_for_flags(
                db,
                message,
                (error.code,),
                existing_case=message.case,
                model_name=analyzer.model_name,
                confidence=None,
            )
        except CompletedCaseReplayBlocked:
            return mark_failed(
                db,
                message_id,
                "COMPLETED_CASE_REPROCESSING_BLOCKED",
                settings=active,
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
    validated, case = _prepare_analysis_routing(
        db,
        message,
        result,
        bundle,
        confidence_threshold=active.ai_auto_apply_confidence_threshold,
        source_flags=source_flags,
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
        try:
            review = _review_for_flags(
                db,
                message,
                validated.flags,
                existing_case=case,
                model_name=analyzer.model_name,
                confidence=result.overall_confidence,
            )
        except CompletedCaseReplayBlocked:
            return mark_failed(
                db,
                message_id,
                "COMPLETED_CASE_REPROCESSING_BLOCKED",
                settings=active,
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
        finalized = _finalize(
            db,
            message,
            analysis,
            validated,
            bundle,
            actor_user_id=None,
        )
    except Exception:
        return mark_failed(db, message_id, "MATERIALIZATION_FAILED", settings=active)
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
    if message.processing_status is ProcessingStatus.FAILED:
        message.processing_next_retry_at = None
        record_audit_event(
            db,
            agency_id=message.agency_id,
            actor_user_id=current.user.id,
            carrier_message_id=message.id,
            event_type="PROCESSING_MANUAL_RETRY",
            description="Manual carrier message retry requested",
            metadata={"previous_attempts": message.processing_attempt_count},
        )
        db.commit()
    return process_message(db, message_id, analyzer=analyzer)


def _evidence_for_human_correction(
    proposed: AnalysisResult,
    correction: HumanAnalysisInput,
    corrected_result: AnalysisResult,
):
    retained = []
    scalar_fields = {
        "classification",
        "summary",
        "priority",
        "client_name",
        "policy_number",
        "policy_status",
        "premium_amount",
        "currency",
        "effective_date",
        "deadline",
    }
    for evidence in proposed.evidence:
        field_name = evidence.field_name
        if field_name in {"client_name", "policy_number"}:
            unchanged = getattr(proposed, field_name) == getattr(correction, field_name)
            if unchanged or evidence_supports_proposed_value(corrected_result, evidence):
                retained.append(evidence)
            continue
        if field_name in scalar_fields:
            if getattr(proposed, field_name) == getattr(correction, field_name):
                retained.append(evidence)
            continue
        action_match = re.fullmatch(r"action_(?:item:|items\[)(\d+)\]?", field_name)
        if action_match:
            index = int(action_match.group(1))
            if (
                index < len(proposed.action_items)
                and index < len(correction.action_items)
                and proposed.action_items[index] == correction.action_items[index]
            ):
                retained.append(evidence)
            continue
        requirement_match = re.fullmatch(r"requirement:(\d+)", field_name)
        if requirement_match:
            index = int(requirement_match.group(1))
            if (
                index < len(proposed.requirements)
                and index < len(correction.requirements)
                and proposed.requirements[index] == correction.requirements[index]
            ):
                retained.append(evidence)
            continue
        retained.append(evidence)
    return retained


def _human_review_case(
    db: Session,
    current: AuthContext,
    review: ReviewItem,
    message: CarrierMessage,
    result: AnalysisResult,
    selected_case_id: int | None = None,
) -> tuple[PolicyCase | None, set[str]]:
    """Resolve a human-reviewed result without applying Gmail handoff semantics."""
    blockers: set[str] = set()
    linked_case = review.case
    if selected_case_id is not None:
        from app.services.operations import scoped_cases_query

        selected = db.scalar(
            scoped_cases_query(current).where(
                PolicyCase.id == selected_case_id,
                PolicyCase.dismissed_at.is_(None),
            )
        )
        candidate_ids = {case.id for case in _case_candidates(db, message, result)}
        if selected is None or selected.id not in candidate_ids:
            blockers.add("CASE_OWNER_CONFLICT")
            return selected, blockers
        review.case_id = selected.id
        review.assigned_reviewer_id = selected.assigned_agent_id
        message.case_id = selected.id
        return selected, blockers
    matched_case = _case_for_result(db, message, result)

    if linked_case is not None:
        if (
            linked_case.agency_id != message.agency_id
            or linked_case.carrier_id != message.carrier_id
            or linked_case.assigned_agent_id != current.user.id
        ):
            blockers.add("CASE_OWNER_CONFLICT")
            return linked_case, blockers
        if matched_case is not None and matched_case.id != linked_case.id:
            blockers.add("CASE_OWNER_CONFLICT")
        return linked_case, blockers

    if matched_case is not None:
        if not _case_has_operational_agent(db, matched_case):
            blockers.add("OPERATIONAL_OWNER_REQUIRED")
        elif matched_case.assigned_agent_id != current.user.id:
            blockers.add("CASE_OWNER_CONFLICT")
        elif result.client_name and _client_key(matched_case.client_name) != _client_key(
            result.client_name
        ):
            blockers.add("CLIENT_MISMATCH")
        if not blockers:
            review.case_id = matched_case.id
            review.assigned_reviewer_id = matched_case.assigned_agent_id
            message.case_id = matched_case.id
        return matched_case, blockers

    if result.classification in POLICY_CLASSIFICATIONS:
        connection_agent_id = _connection_agent_id(db, message)
        if connection_agent_id is None:
            blockers.add("OPERATIONAL_OWNER_REQUIRED")
        elif connection_agent_id != current.user.id:
            blockers.add("CASE_OWNER_CONFLICT")
    elif result.action_items:
        blockers.add("ACTION_WITHOUT_CASE")
    return None, blockers


def _retain_only_verified_human_evidence(validated: ValidatedAnalysis) -> ValidatedAnalysis:
    """Keep final human-reviewed evidence limited to source-verified excerpts."""
    return ValidatedAnalysis(
        result=validated.result.model_copy(
            update={"evidence": [item.proposal for item in validated.verified_evidence]}
        ),
        flags=validated.flags,
        verified_evidence=validated.verified_evidence,
        premium_amount=validated.premium_amount,
        effective_date=validated.effective_date,
        deadline_at=validated.deadline_at,
    )


def reevaluate_stored_review(db: Session, review_id: int) -> ProcessingResult:
    """Re-run deterministic routing for a Review without calling the model provider."""
    review = db.get(ReviewItem, review_id)
    if review is None:
        raise LookupError("Review item not found")
    if review.status not in {ReviewStatus.OPEN, ReviewStatus.IN_REVIEW}:
        raise ValueError("Review is already finalized")
    message = _load_message(db, review.carrier_message_id)
    if message is None or message.analysis is None:
        raise ValueError("Stored analysis is unavailable")
    try:
        result = AnalysisResult.model_validate(message.analysis.model_result_json)
    except ValueError as error:
        raise ValueError("Stored analysis is invalid") from error
    settings = get_settings()
    bundle = build_source_bundle(message, max_chars=settings.ai_max_source_chars)
    validated, case = _prepare_analysis_routing(
        db,
        message,
        result,
        bundle,
        confidence_threshold=settings.ai_auto_apply_confidence_threshold,
    )
    message.analysis.validation_flags = list(validated.flags)
    if not validated.safe_to_apply:
        active_review = _review_for_flags(
            db,
            message,
            validated.flags,
            existing_case=case,
            model_name=message.analysis.model_name,
            confidence=float(message.analysis.overall_confidence),
        )
        return ProcessingResult(
            message_id=message.id,
            processing_status=ProcessingStatus.NEEDS_REVIEW,
            case_id=case.id if case else None,
            review_id=active_review.id,
            analysis_confidence=float(message.analysis.overall_confidence),
            validation_flags=validated.flags,
        )
    return _finalize(
        db,
        message,
        message.analysis,
        validated,
        bundle,
        actor_user_id=None,
        review=review,
    )


def reconcile_stored_discrepancy_tasks(db: Session, message_id: int) -> int:
    """Remove obsolete generic missing-info work when stored analysis already disputes a field."""
    message = _load_message(db, message_id)
    if message is None or message.analysis is None or not message.analysis.final_result_json:
        raise ValueError("Stored finalized analysis is unavailable")
    try:
        result = AnalysisResult.model_validate(message.analysis.final_result_json)
    except ValueError as error:
        raise ValueError("Stored finalized analysis is invalid") from error
    disputed_fields = _disputed_fields_from_actions(result.action_items)
    if not disputed_fields:
        return 0

    actions = list(_without_redundant_missing_actions(result, disputed_fields).action_items)
    for field_name in disputed_fields:
        matching_index = next(
            (
                index
                for index, action in enumerate(actions)
                if _action_declares_discrepancy(action, field_name)
            ),
            None,
        )
        if matching_index is None:
            continue
        action = actions[matching_index]
        title = _DISCREPANCY_TASKS[field_name][0]
        description = action.description or ""
        if "carrier" not in description.casefold():
            description = f"{description.rstrip()} Confirm the correct value with the carrier."
        actions[matching_index] = action.model_copy(
            update={"title": title, "description": description.strip()}
        )

    corrected = result.model_copy(update={"action_items": actions})
    message.analysis.final_result_json = corrected.model_dump(mode="json")
    active_tasks = db.scalars(
        select(Task).where(
            Task.source_carrier_message_id == message.id,
            Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
        )
    ).all()
    dismissed = 0
    redundant_titles = {
        title
        for field_name, title in _REDUNDANT_MISSING_TASKS.items()
        if field_name in disputed_fields
    }
    for task in active_tasks:
        if task.title in redundant_titles:
            task.status = TaskStatus.DISMISSED
            dismissed += 1
            continue
        if task.source_action_index is not None and task.source_action_index < len(actions):
            action = actions[task.source_action_index]
            task.title = action.title
            task.description = action.description
            task.priority = action.priority

    record_audit_event(
        db,
        agency_id=message.agency_id,
        case_id=message.case_id,
        carrier_message_id=message.id,
        event_type="TASKS_RECONCILED",
        description="Redundant missing-information tasks were reconciled",
        metadata={
            "disputed_fields": sorted(disputed_fields),
            "tasks_dismissed": dismissed,
        },
    )
    enqueue_for_message(db, message)
    db.commit()
    return dismissed


def apply_review(
    db: Session,
    current: AuthContext,
    review_id: int,
    correction: HumanAnalysisInput,
    selected_case_id: int | None = None,
) -> ProcessingResult:
    from app.services.operations import get_review_item

    if current.user.role is UserRole.MANAGER:
        raise HTTPException(
            status_code=403,
            detail="Review decisions are completed by the assigned agent",
        )
    get_review_item(db, current, review_id)
    review = db.get(ReviewItem, review_id)
    assert review is not None
    if review.case is not None and review.case.dismissed_at is not None:
        raise HTTPException(status_code=409, detail="Restore this case before resolving its review")
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
            proposed = AnalysisResult.model_validate(original.model_result_json)
            corrected_without_evidence = AnalysisResult(
                **correction.model_dump(),
                evidence=[],
                overall_confidence=confidence,
                uncertainties=[],
            )
            evidence = _evidence_for_human_correction(
                proposed, correction, corrected_without_evidence
            )
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
    validated = _retain_only_verified_human_evidence(validated)
    blocking = post_human_review_blocking_flags(validated.flags)
    if selected_case_id is not None and (
        review.reason_code != "CASE_MATCH_CONFLICT" or review.case_id is not None
    ):
        raise HTTPException(status_code=422, detail="A case selection is not valid for this review")
    if selected_case_id is not None:
        blocking.discard("CASE_MATCH_CONFLICT")
    if review.reason_code == "CASE_MATCH_CONFLICT" and selected_case_id is None:
        raise HTTPException(
            status_code=422,
            detail="Select the matching case before applying this review",
        )
    case, ownership_blockers = _human_review_case(
        db, current, review, message, validated.result, selected_case_id
    )
    blocking.update(ownership_blockers)
    if original is not None and "CASE_OWNER_CONFLICT" in original.validation_flags:
        blocking.add("CASE_OWNER_CONFLICT")
    if blocking:
        issues = [
            {
                "code": code,
                "message": REVIEW_REASONS.get(
                    code, "This issue must be resolved before the review can be applied."
                ),
                "field_name": VALIDATION_FIELDS.get(code),
                "category": (
                    "OWNERSHIP"
                    if code in {"CASE_OWNER_CONFLICT", "OPERATIONAL_OWNER_REQUIRED"}
                    else "VALIDATION"
                ),
                "human_resolvable": code
                not in {"CASE_OWNER_CONFLICT", "OPERATIONAL_OWNER_REQUIRED"},
            }
            for code in sorted(blocking)
        ]
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Resolve the listed issues before applying this review.",
                "issues": issues,
            },
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
        case_override=case,
    )


def dismiss_review(
    db: Session, current: AuthContext, review_id: int, notes: str | None
) -> ProcessingResult:
    from app.services.operations import get_review_item

    if current.user.role is UserRole.MANAGER:
        raise HTTPException(
            status_code=403,
            detail="Review decisions are completed by the assigned agent",
        )
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
    message.processing_next_retry_at = None
    enqueue_for_message(db, message)
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
