from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.audit import AuditEvent
from app.models.enums import (
    AttachmentStatus,
    CaseAssignmentSource,
    GmailConnectionStatus,
    GmailLabelSyncStatus,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
)
from app.models.gmail_labels import GmailManagedLabel, GmailThreadLabelSync
from app.models.operations import (
    Attachment,
    CarrierMessage,
    CaseEvidence,
    PolicyCase,
    ReviewItem,
    Task,
)
from app.models.organization import GmailConnection, GmailOAuthState
from app.services.audit import record_audit_event


@dataclass(frozen=True)
class MailboxReconciliationResult:
    logical_mailboxes: int = 0
    connections_removed: int = 0
    messages_removed: int = 0
    attachments_removed: int = 0
    evidence_removed: int = 0
    reviews_reconciled: int = 0
    tasks_reconciled: int = 0
    label_syncs_removed: int = 0
    cases_reassigned: int = 0
    active_tasks_reassigned: int = 0
    active_reviews_reassigned: int = 0


@dataclass(frozen=True)
class LegacyFanoutReconciliationResult:
    attachments_removed: int = 0
    evidence_removed: int = 0
    dismissed_tasks_removed: int = 0
    duplicate_ingestion_events_preserved: int = 0
    cases_affected: tuple[int, ...] = ()


_MESSAGE_STATUS_RANK = {
    ProcessingStatus.PROCESSED: 5,
    ProcessingStatus.NEEDS_REVIEW: 4,
    ProcessingStatus.PROCESSING: 3,
    ProcessingStatus.RECEIVED: 2,
    ProcessingStatus.FAILED: 1,
    ProcessingStatus.IGNORED: 0,
}
_LABEL_STATUS_RANK = {
    GmailLabelSyncStatus.APPLIED: 5,
    GmailLabelSyncStatus.PENDING: 4,
    GmailLabelSyncStatus.RETRY_WAIT: 3,
    GmailLabelSyncStatus.PROCESSING: 2,
    GmailLabelSyncStatus.NEEDS_PERMISSION: 1,
    GmailLabelSyncStatus.FAILED: 0,
}
_ATTACHMENT_STATUS_RANK = {
    AttachmentStatus.EXTRACTED: 5,
    AttachmentStatus.NEEDS_OCR: 4,
    AttachmentStatus.PENDING: 3,
    AttachmentStatus.FAILED: 2,
    AttachmentStatus.UNSUPPORTED: 1,
}


def _attachment_signature(attachment: Attachment) -> tuple[str, str, int]:
    return (
        attachment.filename.strip().casefold(),
        attachment.mime_type.strip().casefold(),
        attachment.size_bytes,
    )


def _merge_attachment_result(target: Attachment, candidate: Attachment) -> None:
    target_score = (
        _ATTACHMENT_STATUS_RANK[target.processing_status],
        len(target.extracted_text or ""),
        target.page_count or 0,
    )
    candidate_score = (
        _ATTACHMENT_STATUS_RANK[candidate.processing_status],
        len(candidate.extracted_text or ""),
        candidate.page_count or 0,
    )
    if candidate_score <= target_score:
        return
    target.processing_status = candidate.processing_status
    target.extracted_text = candidate.extracted_text
    target.extracted_at = candidate.extracted_at
    target.page_count = candidate.page_count
    target.extraction_error_code = candidate.extraction_error_code


def _merge_duplicate_attachments(
    db: Session, canonical: CarrierMessage, duplicate: CarrierMessage
) -> tuple[dict[int, int], list[Attachment]]:
    canonical_by_signature: dict[tuple[str, str, int], list[Attachment]] = defaultdict(list)
    for attachment in sorted(canonical.attachments, key=lambda item: item.id):
        canonical_by_signature[_attachment_signature(attachment)].append(attachment)
    duplicate_by_signature: dict[tuple[str, str, int], list[Attachment]] = defaultdict(list)
    for attachment in sorted(duplicate.attachments, key=lambda item: item.id):
        duplicate_by_signature[_attachment_signature(attachment)].append(attachment)

    attachment_map: dict[int, int] = {}
    redundant: list[Attachment] = []
    for signature, copies in duplicate_by_signature.items():
        retained = canonical_by_signature[signature]
        for index, copy in enumerate(copies):
            if index < len(retained):
                target = retained[index]
                _merge_attachment_result(target, copy)
                attachment_map[copy.id] = target.id
                redundant.append(copy)
            else:
                copy.carrier_message_id = canonical.id
                retained.append(copy)
                attachment_map[copy.id] = copy.id
    return attachment_map, redundant


def _expected_final_evidence(
    message: CarrierMessage,
) -> list[tuple[str, str, int | None, str]] | None:
    analysis = message.analysis
    if message.case_id is None or analysis is None or analysis.final_result_json is None:
        return None
    attachment_ids = {item.id for item in message.attachments}
    expected: list[tuple[str, str, int | None, str]] = []
    for proposal in analysis.final_result_json.get("evidence", []):
        field_name = proposal.get("field_name")
        excerpt = proposal.get("excerpt")
        source_id = proposal.get("source_id")
        if not isinstance(field_name, str) or not isinstance(excerpt, str):
            continue
        if source_id == "email":
            expected.append((field_name, "EMAIL", None, excerpt))
            continue
        if isinstance(source_id, str) and source_id.startswith("attachment:"):
            try:
                attachment_id = int(source_id.removeprefix("attachment:"))
            except ValueError:
                continue
            if attachment_id in attachment_ids:
                expected.append((field_name, "PDF", attachment_id, excerpt))
    return expected


def _reconcile_finalized_evidence(db: Session, message: CarrierMessage) -> int:
    expected = _expected_final_evidence(message)
    if expected is None:
        return 0
    existing = db.scalars(
        select(CaseEvidence)
        .where(CaseEvidence.carrier_message_id == message.id)
        .order_by(CaseEvidence.id)
    ).all()
    existing_values = [
        (item.field_name, item.source_type, item.attachment_id, item.excerpt) for item in existing
    ]
    if existing_values == expected:
        return 0
    for item in existing:
        db.delete(item)
    for field_name, source_type, attachment_id, excerpt in expected:
        db.add(
            CaseEvidence(
                case_id=message.case_id,
                carrier_message_id=message.id,
                attachment_id=attachment_id,
                field_name=field_name,
                source_type=source_type,
                excerpt=excerpt,
                created_at=utc_now(),
            )
        )
    return max(0, len(existing) - len(expected))


def _message_rank(message: CarrierMessage) -> tuple[int, int, int, int, int]:
    return (
        int(message.case_id is not None),
        int(message.analysis is not None and message.analysis.final_result_json is not None),
        int(message.analysis is not None),
        _MESSAGE_STATUS_RANK[message.processing_status],
        -message.id,
    )


def _merge_duplicate_message(
    db: Session, canonical: CarrierMessage, duplicate: CarrierMessage
) -> tuple[int, int, int, int]:
    db.execute(
        AuditEvent.__table__.update()
        .where(AuditEvent.carrier_message_id == duplicate.id)
        .values(carrier_message_id=canonical.id)
    )

    existing_action_indexes = set(
        db.scalars(
            select(Task.source_action_index).where(
                Task.source_carrier_message_id == canonical.id,
                Task.source_action_index.is_not(None),
            )
        ).all()
    )
    canonical_has_source_tasks = bool(existing_action_indexes)
    duplicate_tasks = db.scalars(
        select(Task).where(Task.source_carrier_message_id == duplicate.id)
    ).all()
    for task in duplicate_tasks:
        if (
            canonical_has_source_tasks
            or task.status in {TaskStatus.COMPLETED, TaskStatus.DISMISSED}
            or task.source_action_index in existing_action_indexes
        ):
            task.source_carrier_message_id = None
            if task.status in {TaskStatus.OPEN, TaskStatus.IN_PROGRESS}:
                task.status = TaskStatus.DISMISSED
        else:
            task.source_carrier_message_id = canonical.id
            existing_action_indexes.add(task.source_action_index)

    active_review_retained = canonical.processing_status is ProcessingStatus.PROCESSED or bool(
        db.scalar(
            select(func.count())
            .select_from(ReviewItem)
            .where(
                ReviewItem.carrier_message_id == canonical.id,
                ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
            )
        )
    )
    duplicate_reviews = db.scalars(
        select(ReviewItem).where(ReviewItem.carrier_message_id == duplicate.id)
    ).all()
    for review in duplicate_reviews:
        review.carrier_message_id = canonical.id
        if review.status in {ReviewStatus.OPEN, ReviewStatus.IN_REVIEW}:
            if active_review_retained:
                review.status = ReviewStatus.DISMISSED
                review.resolution_notes = (
                    "Dismissed during exact Gmail message duplicate reconciliation."
                )
                review.resolved_at = utc_now()
            else:
                active_review_retained = True

    attachment_map, redundant_attachments = _merge_duplicate_attachments(db, canonical, duplicate)
    canonical_evidence = db.scalars(
        select(CaseEvidence).where(CaseEvidence.carrier_message_id == canonical.id)
    ).all()
    duplicate_evidence = db.scalars(
        select(CaseEvidence).where(CaseEvidence.carrier_message_id == duplicate.id)
    ).all()
    preserve_duplicate_set = not canonical_evidence and _expected_final_evidence(canonical) is None
    duplicate_evidence_removed = 0
    for evidence in duplicate_evidence:
        if preserve_duplicate_set:
            evidence.carrier_message_id = canonical.id
            if evidence.attachment_id in attachment_map:
                evidence.attachment_id = attachment_map[evidence.attachment_id]
        else:
            db.delete(evidence)
            duplicate_evidence_removed += 1
    for attachment in redundant_attachments:
        db.delete(attachment)

    db.flush()
    db.delete(duplicate)
    db.flush()
    return (
        len(duplicate_tasks),
        len(duplicate_reviews),
        len(redundant_attachments),
        duplicate_evidence_removed,
    )


def _merge_message_groups(
    db: Session, connections: list[GmailConnection], canonical_connection_id: int
) -> tuple[int, int, int, int, int]:
    connection_ids = [item.id for item in connections]
    messages = db.scalars(
        select(CarrierMessage)
        .where(CarrierMessage.gmail_connection_id.in_(connection_ids))
        .order_by(CarrierMessage.id)
    ).all()
    grouped: dict[str | None, list[CarrierMessage]] = defaultdict(list)
    for message in messages:
        grouped[message.gmail_message_id].append(message)
    removed = 0
    tasks_reconciled = 0
    reviews_reconciled = 0
    attachments_removed = 0
    evidence_removed = 0
    for gmail_message_id, group in grouped.items():
        if gmail_message_id is None:
            for message in group:
                message.gmail_connection_id = canonical_connection_id
            continue
        canonical = max(group, key=_message_rank)
        for duplicate in group:
            if duplicate.id == canonical.id:
                continue
            (
                task_count,
                review_count,
                attachment_count,
                duplicate_evidence_count,
            ) = _merge_duplicate_message(db, canonical, duplicate)
            tasks_reconciled += task_count
            reviews_reconciled += review_count
            attachments_removed += attachment_count
            evidence_removed += duplicate_evidence_count
            removed += 1
        canonical.gmail_connection_id = canonical_connection_id
        evidence_removed += _reconcile_finalized_evidence(db, canonical)
        db.flush()
    return (
        removed,
        tasks_reconciled,
        reviews_reconciled,
        attachments_removed,
        evidence_removed,
    )


def _merge_label_state(
    db: Session, connections: list[GmailConnection], canonical_connection_id: int
) -> int:
    connection_ids = [item.id for item in connections]
    labels = db.scalars(
        select(GmailManagedLabel).where(GmailManagedLabel.gmail_connection_id.in_(connection_ids))
    ).all()
    by_key: dict[object, list[GmailManagedLabel]] = defaultdict(list)
    for label in labels:
        by_key[label.label_key].append(label)
    kept_labels: list[GmailManagedLabel] = []
    for group in by_key.values():
        keep = max(
            group,
            key=lambda item: (
                item.gmail_connection_id == canonical_connection_id,
                item.id,
            ),
        )
        for label in group:
            if label.id != keep.id:
                db.delete(label)
        kept_labels.append(keep)
    db.flush()
    for keep in kept_labels:
        keep.gmail_connection_id = canonical_connection_id
    db.flush()

    syncs = db.scalars(
        select(GmailThreadLabelSync).where(
            GmailThreadLabelSync.gmail_connection_id.in_(connection_ids)
        )
    ).all()
    by_thread: dict[str, list[GmailThreadLabelSync]] = defaultdict(list)
    for sync in syncs:
        by_thread[sync.gmail_thread_id].append(sync)
    removed = 0
    kept_syncs: list[GmailThreadLabelSync] = []
    for group in by_thread.values():
        keep = max(
            group,
            key=lambda item: (
                item.generation,
                _LABEL_STATUS_RANK[item.status],
                item.gmail_connection_id == canonical_connection_id,
                item.id,
            ),
        )
        for sync in group:
            if sync.id != keep.id:
                db.delete(sync)
                removed += 1
        kept_syncs.append(keep)
    db.flush()
    for keep in kept_syncs:
        keep.gmail_connection_id = canonical_connection_id
    db.flush()
    return removed


def reconcile_duplicate_gmail_connections(db: Session) -> MailboxReconciliationResult:
    """Collapse legacy reconnect rows into one stable logical mailbox identity."""
    connections = db.scalars(
        select(GmailConnection).order_by(
            GmailConnection.agency_id, func.lower(GmailConnection.gmail_address), GmailConnection.id
        )
    ).all()
    groups: dict[tuple[int, str], list[GmailConnection]] = defaultdict(list)
    for connection in connections:
        normalized = connection.gmail_address.strip().casefold()
        groups[(connection.agency_id, normalized)].append(connection)

    totals = MailboxReconciliationResult()
    logical_mailboxes = connections_removed = messages_removed = label_syncs_removed = 0
    attachments_removed = evidence_removed = 0
    cases_reassigned = tasks_reassigned = reviews_reassigned = 0
    duplicate_tasks_reconciled = duplicate_reviews_reconciled = 0
    from app.services.message_processing import reconcile_case_operational_ownership

    for (agency_id, gmail_address), group in groups.items():
        if len(group) == 1:
            continue
        logical_mailboxes += 1
        canonical = max(
            group,
            key=lambda item: (
                item.status is not GmailConnectionStatus.DISCONNECTED,
                item.connected_at is not None,
                item.connected_at,
                item.id,
            ),
        )
        former_owner_ids = sorted(
            {item.user_id for item in group if item.user_id != canonical.user_id}
        )
        (
            group_messages_removed,
            group_tasks_reconciled,
            group_reviews_reconciled,
            group_attachments_removed,
            group_evidence_removed,
        ) = _merge_message_groups(db, group, canonical.id)
        group_label_syncs_removed = _merge_label_state(db, group, canonical.id)
        messages_removed += group_messages_removed
        attachments_removed += group_attachments_removed
        evidence_removed += group_evidence_removed
        duplicate_tasks_reconciled += group_tasks_reconciled
        duplicate_reviews_reconciled += group_reviews_reconciled
        label_syncs_removed += group_label_syncs_removed
        group_cases_reassigned = 0
        group_tasks_reassigned = 0
        group_reviews_reassigned = 0

        db.execute(
            GmailOAuthState.__table__.update()
            .where(GmailOAuthState.reconnect_connection_id.in_([item.id for item in group]))
            .values(reconnect_connection_id=canonical.id)
        )
        case_ids = set(
            db.scalars(
                select(CarrierMessage.case_id).where(
                    CarrierMessage.gmail_connection_id == canonical.id,
                    CarrierMessage.case_id.is_not(None),
                )
            ).all()
        )
        if former_owner_ids:
            for case in db.scalars(select(PolicyCase).where(PolicyCase.id.in_(case_ids))).all():
                result = reconcile_case_operational_ownership(
                    db,
                    case,
                    assigned_agent_id=canonical.user_id,
                    assignment_source=CaseAssignmentSource.GMAIL_HANDOFF,
                    actor_user_id=None,
                )
                if result.previous_assignee_id != canonical.user_id:
                    cases_reassigned += 1
                    group_cases_reassigned += 1
                tasks_reassigned += result.active_tasks_reassigned
                reviews_reassigned += result.active_reviews_reassigned
                group_tasks_reassigned += result.active_tasks_reassigned
                group_reviews_reassigned += result.active_reviews_reassigned

        for connection in group:
            if connection.id != canonical.id:
                db.delete(connection)
                connections_removed += 1
        canonical.gmail_address = gmail_address
        record_audit_event(
            db,
            agency_id=agency_id,
            event_type="GMAIL_MAILBOX_IDENTITY_RECONCILED",
            description="Legacy Gmail reconnect records were consolidated safely",
            metadata={
                "gmail_address": gmail_address,
                "connection_id": canonical.id,
                "former_owner_ids": former_owner_ids,
                "new_owner_id": canonical.user_id,
                "connections_removed": len(group) - 1,
                "messages_removed": group_messages_removed,
                "attachments_removed": group_attachments_removed,
                "evidence_removed": group_evidence_removed,
                "tasks_reconciled": group_tasks_reconciled,
                "reviews_reconciled": group_reviews_reconciled,
                "label_syncs_removed": group_label_syncs_removed,
                "cases_reassigned": group_cases_reassigned,
                "active_tasks_reassigned": group_tasks_reassigned,
                "active_reviews_reassigned": group_reviews_reassigned,
            },
        )
        db.flush()

    totals = MailboxReconciliationResult(
        logical_mailboxes=logical_mailboxes,
        connections_removed=connections_removed,
        messages_removed=messages_removed,
        attachments_removed=attachments_removed,
        evidence_removed=evidence_removed,
        reviews_reconciled=duplicate_reviews_reconciled,
        tasks_reconciled=duplicate_tasks_reconciled,
        label_syncs_removed=label_syncs_removed,
        cases_reassigned=cases_reassigned,
        active_tasks_reassigned=tasks_reassigned,
        active_reviews_reassigned=reviews_reassigned,
    )
    return totals


def reconcile_legacy_duplicate_fanout(db: Session) -> LegacyFanoutReconciliationResult:
    """Clean child-row fan-out left by the already-applied mailbox identity migration."""
    identity_events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.event_type == "GMAIL_MAILBOX_IDENTITY_RECONCILED")
        .order_by(AuditEvent.id)
    ).all()
    if not identity_events:
        return LegacyFanoutReconciliationResult()

    attachments_removed = evidence_removed = dismissed_tasks_removed = 0
    duplicate_ingestion_events = 0
    affected_case_ids: set[int] = set()
    processed_agencies: set[int] = set()
    for event in identity_events:
        if event.agency_id in processed_agencies:
            continue
        already_reconciled = db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.agency_id == event.agency_id,
                AuditEvent.event_type == "GMAIL_DUPLICATE_FANOUT_RECONCILED",
            )
        )
        if already_reconciled is not None:
            processed_agencies.add(event.agency_id)
            continue

        agency_events = [item for item in identity_events if item.agency_id == event.agency_id]
        for identity_event in agency_events:
            connection_id = identity_event.event_metadata.get("connection_id")
            if not isinstance(connection_id, int):
                continue
            window_start = identity_event.created_at - timedelta(seconds=10)
            window_end = identity_event.created_at
            candidates = db.scalars(
                select(Attachment)
                .join(CarrierMessage, CarrierMessage.id == Attachment.carrier_message_id)
                .where(
                    CarrierMessage.gmail_connection_id == connection_id,
                    Attachment.updated_at >= window_start,
                    Attachment.updated_at <= window_end,
                )
                .order_by(Attachment.id)
            ).all()
            candidate_ids = {item.id for item in candidates}
            for candidate in candidates:
                siblings = db.scalars(
                    select(Attachment)
                    .where(
                        Attachment.carrier_message_id == candidate.carrier_message_id,
                        Attachment.id.not_in(candidate_ids),
                    )
                    .order_by(Attachment.id)
                ).all()
                retained = next(
                    (
                        item
                        for item in siblings
                        if _attachment_signature(item) == _attachment_signature(candidate)
                    ),
                    None,
                )
                if retained is None:
                    continue
                _merge_attachment_result(retained, candidate)
                for evidence in db.scalars(
                    select(CaseEvidence).where(CaseEvidence.attachment_id == candidate.id)
                ).all():
                    evidence.attachment_id = retained.id
                    affected_case_ids.add(evidence.case_id)
                message = db.get(CarrierMessage, candidate.carrier_message_id)
                if message is not None and message.case_id is not None:
                    affected_case_ids.add(message.case_id)
                db.delete(candidate)
                attachments_removed += 1
            db.flush()

            duplicate_tasks = db.scalars(
                select(Task).where(
                    Task.agency_id == event.agency_id,
                    Task.source_carrier_message_id.is_(None),
                    Task.status == TaskStatus.DISMISSED,
                    Task.updated_at >= window_start,
                    Task.updated_at <= window_end,
                    ~select(AuditEvent.id).where(AuditEvent.task_id == Task.id).exists(),
                )
            ).all()
            for task in duplicate_tasks:
                affected_case_ids.add(task.case_id)
                db.delete(task)
                dismissed_tasks_removed += 1
            db.flush()

        messages = db.scalars(
            select(CarrierMessage)
            .where(CarrierMessage.agency_id == event.agency_id)
            .order_by(CarrierMessage.id)
        ).all()
        for message in messages:
            removed = _reconcile_finalized_evidence(db, message)
            if removed:
                evidence_removed += removed
                if message.case_id is not None:
                    affected_case_ids.add(message.case_id)
        db.flush()

        ingestion_counts = db.execute(
            select(AuditEvent.carrier_message_id, func.count())
            .where(
                AuditEvent.agency_id == event.agency_id,
                AuditEvent.event_type == "GMAIL_MESSAGE_INGESTED",
                AuditEvent.carrier_message_id.is_not(None),
            )
            .group_by(AuditEvent.carrier_message_id)
            .having(func.count() > 1)
        ).all()
        agency_duplicate_ingestions = sum(count - 1 for _, count in ingestion_counts)
        duplicate_ingestion_events += agency_duplicate_ingestions
        record_audit_event(
            db,
            agency_id=event.agency_id,
            event_type="GMAIL_DUPLICATE_FANOUT_RECONCILED",
            description="Duplicate Gmail processing child records were reconciled safely",
            metadata={
                "attachments_removed": attachments_removed,
                "evidence_removed": evidence_removed,
                "dismissed_tasks_removed": dismissed_tasks_removed,
                "duplicate_ingestion_events_preserved": agency_duplicate_ingestions,
                "affected_case_ids": sorted(affected_case_ids),
            },
        )
        processed_agencies.add(event.agency_id)
        db.flush()

    return LegacyFanoutReconciliationResult(
        attachments_removed=attachments_removed,
        evidence_removed=evidence_removed,
        dismissed_tasks_removed=dismissed_tasks_removed,
        duplicate_ingestion_events_preserved=duplicate_ingestion_events,
        cases_affected=tuple(sorted(affected_case_ids)),
    )
