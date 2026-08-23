from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings, get_settings
from app.core.time import utc_now
from app.integrations.gmail.client import GmailMailbox, mailbox_from_credential
from app.integrations.gmail.errors import (
    GmailLabelConflict,
    GmailLabelPermanentError,
    GmailModifyPermissionRequired,
    GmailReauthorizationRequired,
    GmailThreadNotFound,
    GmailTransientError,
)
from app.integrations.gmail.oauth import GMAIL_MODIFY_SCOPE
from app.models.enums import (
    AuditSeverity,
    GmailConnectionStatus,
    GmailLabelKey,
    GmailLabelSyncStatus,
    MessageClassification,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
    UserRole,
)
from app.models.gmail_labels import GmailManagedLabel, GmailThreadLabelSync
from app.models.operations import CarrierMessage, PolicyCase, ReviewItem, Task
from app.models.organization import GmailConnection, GmailOAuthCredential, User
from app.services.audit import record_audit_event

MailboxFactory = Callable[[GmailOAuthCredential], tuple[GmailMailbox, bool]]

MANAGED_LABEL_NAMES: dict[GmailLabelKey, str] = {
    GmailLabelKey.PROCESSING: "AI: Processing",
    GmailLabelKey.ACTION_REQUIRED: "AI: Action Required",
    GmailLabelKey.POLICY_ISSUED: "AI: Policy Issued",
    GmailLabelKey.PENDING_REQUIREMENTS: "AI: Pending Requirements",
    GmailLabelKey.LAPSE_NOTICE: "AI: Lapse Notice",
    GmailLabelKey.COMMISSION_UPDATE: "AI: Commission Update",
    GmailLabelKey.NEEDS_REVIEW: "AI: Needs Review",
    GmailLabelKey.NO_FURTHER_ACTION_NEEDED: "AI: No Further Action Needed",
    GmailLabelKey.FAILED: "AI: Failed",
}

LEGACY_MANAGED_LABEL_NAMES: dict[GmailLabelKey, str] = {
    GmailLabelKey.PROCESSED: "Processed",
}

RECONCILABLE_LABEL_NAMES = MANAGED_LABEL_NAMES | LEGACY_MANAGED_LABEL_NAMES

WORKFLOW_LABEL_KEYS = frozenset(
    {
        GmailLabelKey.PROCESSING,
        GmailLabelKey.NEEDS_REVIEW,
        GmailLabelKey.ACTION_REQUIRED,
        GmailLabelKey.NO_FURTHER_ACTION_NEEDED,
        GmailLabelKey.FAILED,
    }
)

CLASSIFICATION_LABEL_KEYS = frozenset(
    {
        GmailLabelKey.POLICY_ISSUED,
        GmailLabelKey.PENDING_REQUIREMENTS,
        GmailLabelKey.LAPSE_NOTICE,
        GmailLabelKey.COMMISSION_UPDATE,
    }
)

CLASSIFICATION_LABELS = {
    MessageClassification.POLICY_ISSUED: GmailLabelKey.POLICY_ISSUED,
    MessageClassification.PENDING_REQUIREMENTS: GmailLabelKey.PENDING_REQUIREMENTS,
    MessageClassification.LAPSE_NOTICE: GmailLabelKey.LAPSE_NOTICE,
    MessageClassification.COMMISSION_UPDATE: GmailLabelKey.COMMISSION_UPDATE,
}


def _enforce_label_invariant(desired: set[GmailLabelKey]) -> None:
    if (
        len(desired & WORKFLOW_LABEL_KEYS) > 1
        or len(desired & CLASSIFICATION_LABEL_KEYS) > 1
        or len(desired) > 2
    ):
        raise RuntimeError("Gmail thread desired state exceeds the managed two-label invariant")


@dataclass(frozen=True)
class LabelClaim:
    sync_id: int
    generation: int


@dataclass(frozen=True)
class LabelResult:
    sync_id: int
    status: GmailLabelSyncStatus
    generation: int
    desired_label_keys: tuple[GmailLabelKey, ...] = ()
    added: int = 0
    removed: int = 0
    obsolete_processed_removed: int = 0


def can_apply_workflow_labels(connection: GmailConnection) -> bool:
    credential = connection.oauth_credential
    return bool(credential and GMAIL_MODIFY_SCOPE in credential.granted_scopes)


def enqueue_thread_label_sync(
    db: Session,
    *,
    agency_id: int,
    gmail_connection_id: int | None,
    gmail_thread_id: str | None,
    record_event: bool = True,
) -> GmailThreadLabelSync | None:
    if gmail_connection_id is None or not gmail_thread_id:
        return None
    sync = db.scalar(
        select(GmailThreadLabelSync)
        .where(
            GmailThreadLabelSync.gmail_connection_id == gmail_connection_id,
            GmailThreadLabelSync.gmail_thread_id == gmail_thread_id,
        )
        .with_for_update()
    )
    if sync is None:
        inserted_id = db.scalar(
            pg_insert(GmailThreadLabelSync)
            .values(
                agency_id=agency_id,
                gmail_connection_id=gmail_connection_id,
                gmail_thread_id=gmail_thread_id,
                status=GmailLabelSyncStatus.PENDING,
                generation=1,
                attempt_count=0,
                applied_label_keys=[],
            )
            .on_conflict_do_nothing(index_elements=["gmail_connection_id", "gmail_thread_id"])
            .returning(GmailThreadLabelSync.id)
        )
        if inserted_id is not None:
            sync = db.get(GmailThreadLabelSync, inserted_id)
            assert sync is not None
        else:
            sync = db.scalar(
                select(GmailThreadLabelSync)
                .where(
                    GmailThreadLabelSync.gmail_connection_id == gmail_connection_id,
                    GmailThreadLabelSync.gmail_thread_id == gmail_thread_id,
                )
                .with_for_update()
            )
            assert sync is not None
            sync.generation += 1
            sync.status = GmailLabelSyncStatus.PENDING
            sync.attempt_count = 0
            sync.processing_started_at = None
            sync.claimed_generation = None
            sync.next_retry_at = None
            sync.last_error_code = None
    else:
        sync.generation += 1
        sync.status = GmailLabelSyncStatus.PENDING
        sync.attempt_count = 0
        sync.processing_started_at = None
        sync.claimed_generation = None
        sync.next_retry_at = None
        sync.last_error_code = None
    if record_event:
        record_audit_event(
            db,
            agency_id=agency_id,
            event_type="GMAIL_WORKFLOW_LABELS_PENDING",
            description="Gmail workflow label reconciliation is pending",
            metadata={"connection_id": gmail_connection_id},
        )
    return sync


def enqueue_for_message(
    db: Session, message: CarrierMessage, *, record_event: bool = True
) -> GmailThreadLabelSync | None:
    return enqueue_thread_label_sync(
        db,
        agency_id=message.agency_id,
        gmail_connection_id=message.gmail_connection_id,
        gmail_thread_id=message.gmail_thread_id,
        record_event=record_event,
    )


def enqueue_for_case(
    db: Session, *, agency_id: int, case_id: int, record_event: bool = True
) -> int:
    identities = db.execute(
        select(
            CarrierMessage.gmail_connection_id,
            CarrierMessage.gmail_thread_id,
        )
        .where(
            CarrierMessage.case_id == case_id,
            CarrierMessage.gmail_connection_id.is_not(None),
            CarrierMessage.gmail_thread_id.is_not(None),
            CarrierMessage.gmail_thread_id != "",
        )
        .distinct()
    ).all()
    for connection_id, thread_id in identities:
        enqueue_thread_label_sync(
            db,
            agency_id=agency_id,
            gmail_connection_id=connection_id,
            gmail_thread_id=thread_id,
            record_event=record_event,
        )
    return len(identities)


def backfill_thread_label_syncs(db: Session) -> int:
    identities = db.execute(
        select(
            CarrierMessage.agency_id,
            CarrierMessage.gmail_connection_id,
            CarrierMessage.gmail_thread_id,
        )
        .where(
            CarrierMessage.gmail_connection_id.is_not(None),
            CarrierMessage.gmail_thread_id.is_not(None),
            CarrierMessage.gmail_thread_id != "",
        )
        .distinct()
    ).all()
    created = 0
    for agency_id, connection_id, thread_id in identities:
        exists = db.scalar(
            select(GmailThreadLabelSync.id).where(
                GmailThreadLabelSync.gmail_connection_id == connection_id,
                GmailThreadLabelSync.gmail_thread_id == thread_id,
            )
        )
        if exists is None:
            enqueue_thread_label_sync(
                db,
                agency_id=agency_id,
                gmail_connection_id=connection_id,
                gmail_thread_id=thread_id,
                record_event=False,
            )
            created += 1
    db.commit()
    return created


def desired_labels_for_thread(
    db: Session, *, gmail_connection_id: int, gmail_thread_id: str
) -> set[GmailLabelKey]:
    messages = db.scalars(
        select(CarrierMessage)
        .where(
            CarrierMessage.gmail_connection_id == gmail_connection_id,
            CarrierMessage.gmail_thread_id == gmail_thread_id,
        )
        .order_by(CarrierMessage.received_at, CarrierMessage.id)
    ).all()
    if not messages:
        return set()
    message_ids = [message.id for message in messages]
    active_agent_for_review = exists(
        select(User.id).where(
            User.id == ReviewItem.assigned_reviewer_id,
            User.role == UserRole.AGENT,
            User.is_active.is_(True),
            User.removed_at.is_(None),
        )
    )
    active_review = db.scalar(
        select(ReviewItem.id)
        .join(PolicyCase, ReviewItem.case_id == PolicyCase.id, isouter=True)
        .where(
            ReviewItem.carrier_message_id.in_(message_ids),
            ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
            or_(
                and_(ReviewItem.case_id.is_(None), active_agent_for_review),
                and_(
                    ReviewItem.case_id.is_not(None),
                    PolicyCase.dismissed_at.is_(None),
                    PolicyCase.completed_at.is_(None),
                ),
            ),
        )
        .limit(1)
    )
    active_source_task = db.scalar(
        select(Task.id)
        .join(PolicyCase, Task.case_id == PolicyCase.id)
        .where(
            Task.source_carrier_message_id.in_(message_ids),
            Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
            PolicyCase.dismissed_at.is_(None),
            PolicyCase.completed_at.is_(None),
        )
        .limit(1)
    )
    terminal_failure = any(
        message.processing_status is ProcessingStatus.FAILED
        and message.processing_next_retry_at is None
        for message in messages
    )
    processing = any(
        message.processing_status in {ProcessingStatus.RECEIVED, ProcessingStatus.PROCESSING}
        or (
            message.processing_status is ProcessingStatus.FAILED
            and message.processing_next_retry_at is not None
        )
        for message in messages
    )
    successfully_analyzed = any(
        message.processing_status in {ProcessingStatus.PROCESSED, ProcessingStatus.NEEDS_REVIEW}
        for message in messages
    )

    workflow_label: GmailLabelKey | None
    if terminal_failure:
        workflow_label = GmailLabelKey.FAILED
    elif active_review is not None:
        workflow_label = GmailLabelKey.NEEDS_REVIEW
    elif active_source_task is not None:
        workflow_label = GmailLabelKey.ACTION_REQUIRED
    elif processing:
        workflow_label = GmailLabelKey.PROCESSING
    elif successfully_analyzed:
        workflow_label = GmailLabelKey.NO_FURTHER_ACTION_NEEDED
    else:
        workflow_label = None

    desired = {workflow_label} if workflow_label is not None else set()
    latest_classified = next(
        (
            message
            for message in reversed(messages)
            if message.processing_status
            in {ProcessingStatus.PROCESSED, ProcessingStatus.NEEDS_REVIEW}
            and message.classification is not None
        ),
        None,
    )
    if latest_classified is not None:
        classification_label = CLASSIFICATION_LABELS.get(latest_classified.classification)
        if classification_label is not None:
            desired.add(classification_label)

    _enforce_label_invariant(desired)
    return desired


def _listed_user_labels(response: Mapping) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in response.get("labels", []) or []:
        if not isinstance(item, Mapping) or item.get("type") != "user":
            continue
        name = item.get("name")
        label_id = item.get("id")
        if (
            isinstance(name, str)
            and isinstance(label_id, str)
            and name in RECONCILABLE_LABEL_NAMES.values()
        ):
            labels[name] = label_id
    return labels


def ensure_managed_labels(
    db: Session, connection: GmailConnection, mailbox: GmailMailbox
) -> dict[GmailLabelKey, str]:
    listed = _listed_user_labels(mailbox.list_labels())
    for key, name in MANAGED_LABEL_NAMES.items():
        if name in listed:
            continue
        try:
            created = mailbox.create_label(name)
            label_id = created.get("id")
            if not isinstance(label_id, str) or not label_id:
                raise GmailLabelPermanentError("Gmail did not return a managed label ID.")
            listed[name] = label_id
            record_audit_event(
                db,
                agency_id=connection.agency_id,
                event_type="GMAIL_MANAGED_LABEL_CREATED",
                description="Carrier Hub managed Gmail label created",
                metadata={"connection_id": connection.id, "label_key": key.value},
            )
        except GmailLabelConflict:
            listed = _listed_user_labels(mailbox.list_labels())
            if name not in listed:
                raise GmailTransientError("Managed Gmail label creation raced safely.") from None

    bindings: dict[GmailLabelKey, str] = {}
    bound_names = {
        key: name
        for key, name in RECONCILABLE_LABEL_NAMES.items()
        if key in MANAGED_LABEL_NAMES or name in listed
    }
    for key, name in bound_names.items():
        label_id = listed[name]
        db.execute(
            pg_insert(GmailManagedLabel)
            .values(
                agency_id=connection.agency_id,
                gmail_connection_id=connection.id,
                label_key=key,
                label_name=name,
                gmail_label_id=label_id,
            )
            .on_conflict_do_update(
                index_elements=["gmail_connection_id", "label_key"],
                set_={"label_name": name, "gmail_label_id": label_id},
            )
        )
        bindings[key] = label_id
    db.commit()
    return bindings


def claim_label_sync(
    db: Session,
    *,
    sync_id: int | None = None,
    connection_id: int | None = None,
) -> LabelClaim | None:
    now = utc_now()
    query = (
        select(GmailThreadLabelSync)
        .where(
            or_(
                GmailThreadLabelSync.status == GmailLabelSyncStatus.PENDING,
                and_(
                    GmailThreadLabelSync.status == GmailLabelSyncStatus.RETRY_WAIT,
                    GmailThreadLabelSync.next_retry_at <= now,
                ),
            )
        )
        .order_by(GmailThreadLabelSync.updated_at, GmailThreadLabelSync.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if sync_id is not None:
        query = query.where(GmailThreadLabelSync.id == sync_id)
    if connection_id is not None:
        query = query.where(GmailThreadLabelSync.gmail_connection_id == connection_id)
    sync = db.scalar(query)
    if sync is None:
        db.rollback()
        return None
    sync.status = GmailLabelSyncStatus.PROCESSING
    sync.claimed_generation = sync.generation
    sync.attempt_count += 1
    sync.processing_started_at = now
    sync.last_attempted_at = now
    sync.next_retry_at = None
    claim = LabelClaim(sync.id, sync.generation)
    db.commit()
    return claim


def _label_backoff(settings: Settings, attempt: int) -> timedelta:
    seconds = min(
        settings.gmail_label_retry_base_seconds * (2 ** max(attempt - 1, 0)),
        settings.gmail_label_retry_max_seconds,
    )
    return timedelta(seconds=seconds)


def _finish_label_failure(
    db: Session,
    claim: LabelClaim,
    code: str,
    *,
    settings: Settings,
    permission: bool = False,
    permanent: bool = False,
) -> LabelResult:
    db.rollback()
    sync = db.get(GmailThreadLabelSync, claim.sync_id)
    if sync is None:
        raise LookupError("Gmail label synchronization state not found")
    if sync.generation != claim.generation:
        return LabelResult(sync.id, sync.status, sync.generation)
    now = utc_now()
    sync.processing_started_at = None
    sync.claimed_generation = None
    sync.last_error_code = code
    if permission:
        sync.status = GmailLabelSyncStatus.NEEDS_PERMISSION
        sync.next_retry_at = None
        event_type = "GMAIL_LABEL_PERMISSION_REQUIRED"
    elif permanent or sync.attempt_count >= settings.gmail_label_max_attempts:
        sync.status = GmailLabelSyncStatus.FAILED
        sync.next_retry_at = None
        if not permanent:
            sync.last_error_code = "GMAIL_LABEL_RETRY_EXHAUSTED"
        event_type = "GMAIL_LABEL_RETRY_EXHAUSTED"
    else:
        sync.status = GmailLabelSyncStatus.RETRY_WAIT
        sync.next_retry_at = now + _label_backoff(settings, sync.attempt_count)
        event_type = "GMAIL_LABEL_RETRY_SCHEDULED"
    record_audit_event(
        db,
        agency_id=sync.agency_id,
        event_type=event_type,
        severity=AuditSeverity.WARNING,
        description="Gmail workflow label delivery requires attention",
        metadata={
            "connection_id": sync.gmail_connection_id,
            "attempt": sync.attempt_count,
            "error_code": sync.last_error_code,
        },
    )
    db.commit()
    return LabelResult(sync.id, sync.status, sync.generation)


def process_claimed_label_sync(
    db: Session,
    claim: LabelClaim,
    *,
    settings: Settings | None = None,
    mailbox_factory: MailboxFactory = mailbox_from_credential,
) -> LabelResult:
    active = settings or get_settings()
    sync = db.scalar(
        select(GmailThreadLabelSync)
        .options(
            joinedload(GmailThreadLabelSync.connection).joinedload(GmailConnection.oauth_credential)
        )
        .where(GmailThreadLabelSync.id == claim.sync_id)
    )
    if sync is None:
        raise LookupError("Gmail label synchronization state not found")
    connection = sync.connection
    if not can_apply_workflow_labels(connection) or connection.oauth_credential is None:
        return _finish_label_failure(
            db,
            claim,
            "GMAIL_MODIFY_SCOPE_REQUIRED",
            settings=active,
            permission=True,
        )
    desired = desired_labels_for_thread(
        db,
        gmail_connection_id=sync.gmail_connection_id,
        gmail_thread_id=sync.gmail_thread_id,
    )
    try:
        mailbox, refreshed = mailbox_factory(connection.oauth_credential)
        if refreshed:
            db.commit()
        bindings = ensure_managed_labels(db, connection, mailbox)
        actual = mailbox.get_thread_label_state(sync.gmail_thread_id)
        managed_ids = set(bindings.values())
        desired_ids = {bindings[key] for key in desired}
        add_ids = (
            sorted(desired_ids - actual.all_label_ids) if actual.labelable_message_count else []
        )
        remove_ids = sorted((actual.any_label_ids & managed_ids) - desired_ids)
        obsolete_processed_id = bindings.get(GmailLabelKey.PROCESSED)
        obsolete_processed_removed = int(
            obsolete_processed_id is not None and obsolete_processed_id in remove_ids
        )
        if add_ids or remove_ids:
            mailbox.modify_thread_labels(
                sync.gmail_thread_id,
                add_label_ids=add_ids,
                remove_label_ids=remove_ids,
            )
    except GmailModifyPermissionRequired:
        return _finish_label_failure(
            db,
            claim,
            "GMAIL_MODIFY_SCOPE_REQUIRED",
            settings=active,
            permission=True,
        )
    except GmailReauthorizationRequired:
        connection.status = GmailConnectionStatus.NEEDS_REAUTH
        db.commit()
        return _finish_label_failure(
            db,
            claim,
            "GMAIL_LABEL_REAUTH_REQUIRED",
            settings=active,
            permission=True,
        )
    except GmailThreadNotFound:
        return _finish_label_failure(
            db,
            claim,
            "GMAIL_THREAD_NOT_FOUND",
            settings=active,
            permanent=True,
        )
    except GmailLabelPermanentError:
        return _finish_label_failure(
            db,
            claim,
            "GMAIL_THREAD_LABEL_FAILED",
            settings=active,
            permanent=True,
        )
    except GmailTransientError:
        return _finish_label_failure(
            db,
            claim,
            "GMAIL_THREAD_LABEL_FAILED",
            settings=active,
        )

    db.rollback()
    current = db.get(GmailThreadLabelSync, claim.sync_id)
    if current is None:
        raise LookupError("Gmail label synchronization state not found")
    if current.generation != claim.generation:
        return LabelResult(current.id, current.status, current.generation)
    current.processing_started_at = None
    current.claimed_generation = None
    current.applied_label_keys = sorted(key.value for key in desired)
    current.last_applied_at = utc_now()
    current.last_error_code = None
    current.next_retry_at = None
    current.status = GmailLabelSyncStatus.APPLIED
    record_audit_event(
        db,
        agency_id=current.agency_id,
        event_type="GMAIL_WORKFLOW_LABELS_APPLIED",
        description="Gmail workflow labels reconciled",
        metadata={
            "connection_id": current.gmail_connection_id,
            "label_keys": sorted(key.value for key in desired),
        },
    )
    db.commit()
    return LabelResult(
        current.id,
        current.status,
        current.generation,
        tuple(sorted(desired, key=lambda item: item.value)),
        len(add_ids),
        len(remove_ids),
        obsolete_processed_removed,
    )


def recover_stale_label_syncs(db: Session, *, settings: Settings | None = None) -> int:
    active = settings or get_settings()
    cutoff = utc_now() - timedelta(seconds=active.gmail_label_stale_after_seconds)
    rows = db.scalars(
        select(GmailThreadLabelSync)
        .where(
            GmailThreadLabelSync.status == GmailLabelSyncStatus.PROCESSING,
            GmailThreadLabelSync.processing_started_at < cutoff,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for sync in rows:
        sync.generation += 1
        sync.status = GmailLabelSyncStatus.PENDING
        sync.processing_started_at = None
        sync.claimed_generation = None
        sync.next_retry_at = None
        sync.last_error_code = "GMAIL_LABEL_STALE_RECOVERED"
        record_audit_event(
            db,
            agency_id=sync.agency_id,
            event_type="GMAIL_LABEL_STALE_RECOVERED",
            severity=AuditSeverity.WARNING,
            description="Stale Gmail label work recovered",
            metadata={"connection_id": sync.gmail_connection_id},
        )
    db.commit()
    return len(rows)


def reset_connection_label_syncs(db: Session, connection_id: int) -> int:
    rows = db.scalars(
        select(GmailThreadLabelSync)
        .where(GmailThreadLabelSync.gmail_connection_id == connection_id)
        .with_for_update()
    ).all()
    for sync in rows:
        sync.generation += 1
        sync.status = GmailLabelSyncStatus.PENDING
        sync.attempt_count = 0
        sync.processing_started_at = None
        sync.claimed_generation = None
        sync.next_retry_at = None
        sync.last_error_code = None
    db.commit()
    return len(rows)


def retry_label_sync(db: Session, sync: GmailThreadLabelSync) -> None:
    sync.generation += 1
    sync.status = GmailLabelSyncStatus.PENDING
    sync.attempt_count = 0
    sync.processing_started_at = None
    sync.claimed_generation = None
    sync.next_retry_at = None
    sync.last_error_code = None
    db.commit()
