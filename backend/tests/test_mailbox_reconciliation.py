from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.audit import AuditEvent
from app.models.carriers import Carrier
from app.models.enums import (
    AttachmentStatus,
    AuditSeverity,
    GmailConnectionStatus,
    GmailLabelSyncStatus,
    MessageClassification,
    PolicyStatus,
    Priority,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
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
from app.models.organization import GmailConnection, User
from app.services.mailbox_reconciliation import (
    reconcile_duplicate_gmail_connections,
    reconcile_legacy_duplicate_fanout,
    reconcile_review_consistency,
    reconcile_single_review_per_message,
)


def test_legacy_reconnect_duplicates_collapse_to_one_logical_mailbox(
    seeded_db: Session,
) -> None:
    db = seeded_db
    db.execute(text("ALTER TABLE gmail_connections DROP CONSTRAINT uq_gmail_agency_address"))
    first_owner = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    current_owner = db.scalar(select(User).where(User.email == "agent.two@demo.local"))
    carrier = db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    assert first_owner is not None and current_owner is not None and carrier is not None
    old = GmailConnection(
        agency_id=first_owner.agency_id,
        user_id=first_owner.id,
        gmail_address="Stable.Mailbox@Gmail.Test",
        status=GmailConnectionStatus.DISCONNECTED,
    )
    current = GmailConnection(
        agency_id=current_owner.agency_id,
        user_id=current_owner.id,
        gmail_address="stable.mailbox@gmail.test",
        status=GmailConnectionStatus.CONNECTED,
        connected_at=utc_now(),
    )
    db.add_all([old, current])
    db.flush()
    case = PolicyCase(
        agency_id=first_owner.agency_id,
        carrier_id=carrier.id,
        assigned_agent_id=current_owner.id,
        client_name="Canonical Client",
        policy_number="CANONICAL-100",
        current_policy_status=PolicyStatus.ISSUED,
        priority=Priority.NORMAL,
        summary="Canonical case.",
    )
    db.add(case)
    db.flush()
    good = CarrierMessage(
        agency_id=first_owner.agency_id,
        case_id=case.id,
        carrier_id=carrier.id,
        gmail_connection_id=old.id,
        gmail_message_id="same-gmail-message",
        gmail_thread_id="same-gmail-thread",
        sender="notices@americo.test",
        subject="Canonical message",
        received_at=utc_now(),
        classification=MessageClassification.POLICY_ISSUED,
        summary="Canonical message.",
        priority=Priority.NORMAL,
        processing_status=ProcessingStatus.PROCESSED,
        raw_content="Synthetic content.",
        cleaned_content="Synthetic content.",
    )
    failed = CarrierMessage(
        agency_id=current_owner.agency_id,
        carrier_id=carrier.id,
        gmail_connection_id=current.id,
        gmail_message_id="same-gmail-message",
        gmail_thread_id="same-gmail-thread",
        sender="notices@americo.test",
        subject="Duplicate message",
        received_at=utc_now(),
        processing_status=ProcessingStatus.FAILED,
        raw_content="Synthetic content.",
        cleaned_content="Synthetic content.",
        last_processing_error_code="MATERIALIZATION_FAILED",
    )
    db.add_all([good, failed])
    db.flush()
    canonical_attachment = Attachment(
        carrier_message_id=good.id,
        external_id="canonical-attachment",
        filename="notice.pdf",
        mime_type="application/pdf",
        size_bytes=100,
        processing_status=AttachmentStatus.PENDING,
    )
    duplicate_attachment = Attachment(
        carrier_message_id=failed.id,
        external_id="duplicate-provider-id",
        filename="notice.pdf",
        mime_type="application/pdf",
        size_bytes=100,
        processing_status=AttachmentStatus.EXTRACTED,
        extracted_text="Successfully extracted synthetic text.",
        page_count=2,
        extracted_at=utc_now(),
    )
    db.add_all([canonical_attachment, duplicate_attachment])
    db.flush()
    db.add(
        MessageAnalysis(
            carrier_message_id=good.id,
            model_name="synthetic-model",
            schema_version="test",
            prompt_version="test",
            overall_confidence=Decimal("0.9000"),
            model_result_json={},
            validation_flags=[],
            final_result_json={
                "evidence": [
                    {
                        "field_name": "client_name",
                        "source_id": f"attachment:{canonical_attachment.id}",
                        "excerpt": "Canonical Client",
                    }
                ]
            },
            finalized_at=utc_now(),
        )
    )
    db.add_all(
        [
            CaseEvidence(
                case_id=case.id,
                carrier_message_id=good.id,
                attachment_id=canonical_attachment.id,
                field_name="client_name",
                source_type="PDF",
                excerpt="Canonical Client",
                created_at=utc_now(),
            ),
            CaseEvidence(
                case_id=case.id,
                carrier_message_id=failed.id,
                attachment_id=duplicate_attachment.id,
                field_name="client_name",
                source_type="PDF",
                excerpt="Nondeterministic duplicate wording",
                created_at=utc_now(),
            ),
            Task(
                agency_id=case.agency_id,
                case_id=case.id,
                source_carrier_message_id=good.id,
                source_action_index=0,
                assigned_agent_id=current_owner.id,
                title="Canonical action",
                priority=Priority.NORMAL,
                status=TaskStatus.OPEN,
            ),
            Task(
                agency_id=case.agency_id,
                case_id=case.id,
                source_carrier_message_id=failed.id,
                source_action_index=0,
                assigned_agent_id=current_owner.id,
                title="Duplicate action wording",
                priority=Priority.NORMAL,
                status=TaskStatus.OPEN,
            ),
        ]
    )
    duplicate_review = ReviewItem(
        agency_id=current_owner.agency_id,
        carrier_message_id=failed.id,
        assigned_reviewer_id=current_owner.id,
        status=ReviewStatus.OPEN,
        reason_code="DUPLICATE_TEST",
        reason="Synthetic duplicate review.",
    )
    db.add_all(
        [
            duplicate_review,
            GmailThreadLabelSync(
                agency_id=first_owner.agency_id,
                gmail_connection_id=old.id,
                gmail_thread_id="same-gmail-thread",
                status=GmailLabelSyncStatus.APPLIED,
            ),
            GmailThreadLabelSync(
                agency_id=current_owner.agency_id,
                gmail_connection_id=current.id,
                gmail_thread_id="same-gmail-thread",
                status=GmailLabelSyncStatus.FAILED,
            ),
        ]
    )
    db.flush()

    result = reconcile_duplicate_gmail_connections(db)
    db.flush()

    assert result.logical_mailboxes == 1
    assert result.connections_removed == 1
    assert result.messages_removed == 1
    assert result.attachments_removed == 1
    assert result.evidence_removed == 1
    assert result.tasks_reconciled == 1
    assert result.label_syncs_removed == 1
    remaining = db.scalars(
        select(GmailConnection).where(
            func.lower(GmailConnection.gmail_address) == "stable.mailbox@gmail.test"
        )
    ).all()
    assert [item.id for item in remaining] == [current.id]
    message = db.scalar(
        select(CarrierMessage).where(CarrierMessage.gmail_message_id == "same-gmail-message")
    )
    assert message is not None
    assert message.id == good.id
    assert message.gmail_connection_id == current.id
    attachments = db.scalars(
        select(Attachment).where(Attachment.carrier_message_id == message.id)
    ).all()
    assert len(attachments) == 1
    assert attachments[0].processing_status is AttachmentStatus.EXTRACTED
    assert attachments[0].extracted_text == "Successfully extracted synthetic text."
    evidence = db.scalars(
        select(CaseEvidence).where(CaseEvidence.carrier_message_id == message.id)
    ).all()
    assert [(item.field_name, item.excerpt) for item in evidence] == [
        ("client_name", "Canonical Client")
    ]
    source_tasks = db.scalars(
        select(Task).where(Task.source_carrier_message_id == message.id)
    ).all()
    assert [(item.source_action_index, item.title) for item in source_tasks] == [
        (0, "Canonical action")
    ]
    assert (
        db.scalar(
            select(func.count())
            .select_from(MessageAnalysis)
            .where(MessageAnalysis.carrier_message_id == message.id)
        )
        == 1
    )
    assert db.get(ReviewItem, duplicate_review.id) is None
    assert (
        db.scalar(
            select(func.count())
            .select_from(GmailThreadLabelSync)
            .where(GmailThreadLabelSync.gmail_thread_id == "same-gmail-thread")
        )
        == 1
    )


def test_followup_reconciliation_removes_only_unhistorical_legacy_fanout(
    seeded_db: Session,
) -> None:
    db = seeded_db
    owner = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    carrier = db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    assert owner is not None and carrier is not None
    connection = GmailConnection(
        agency_id=owner.agency_id,
        user_id=owner.id,
        gmail_address="fanout-cleanup@gmail.test",
        status=GmailConnectionStatus.CONNECTED,
    )
    case = PolicyCase(
        agency_id=owner.agency_id,
        carrier_id=carrier.id,
        assigned_agent_id=owner.id,
        client_name="Fanout Cleanup",
        policy_number="FANOUT-100",
        current_policy_status=PolicyStatus.ISSUED,
        priority=Priority.NORMAL,
        summary="Synthetic cleanup case.",
    )
    db.add_all([connection, case])
    db.flush()
    message = CarrierMessage(
        agency_id=owner.agency_id,
        case_id=case.id,
        carrier_id=carrier.id,
        gmail_connection_id=connection.id,
        gmail_message_id="fanout-message",
        sender="notices@americo.test",
        subject="Fanout cleanup",
        received_at=utc_now(),
        classification=MessageClassification.POLICY_ISSUED,
        summary="Synthetic cleanup message.",
        priority=Priority.NORMAL,
        processing_status=ProcessingStatus.PROCESSED,
        raw_content="Client: Fanout Cleanup",
        cleaned_content="Client: Fanout Cleanup",
    )
    db.add(message)
    db.flush()
    retained_attachment = Attachment(
        carrier_message_id=message.id,
        external_id="retained",
        filename="same.pdf",
        mime_type="application/pdf",
        size_bytes=200,
        processing_status=AttachmentStatus.PENDING,
    )
    duplicate_attachment = Attachment(
        carrier_message_id=message.id,
        external_id="legacy-moved-copy",
        filename="same.pdf",
        mime_type="application/pdf",
        size_bytes=200,
        processing_status=AttachmentStatus.EXTRACTED,
        extracted_text="Better stored extraction.",
        page_count=1,
        extracted_at=utc_now(),
    )
    db.add_all([retained_attachment, duplicate_attachment])
    db.flush()
    db.add(
        MessageAnalysis(
            carrier_message_id=message.id,
            model_name="synthetic-model",
            schema_version="test",
            prompt_version="test",
            overall_confidence=Decimal("0.9000"),
            model_result_json={},
            validation_flags=[],
            final_result_json={
                "evidence": [
                    {
                        "field_name": "client_name",
                        "source_id": "email",
                        "excerpt": "Fanout Cleanup",
                    }
                ]
            },
            finalized_at=utc_now(),
        )
    )
    db.add_all(
        [
            CaseEvidence(
                case_id=case.id,
                carrier_message_id=message.id,
                field_name="client_name",
                source_type="EMAIL",
                excerpt="Fanout Cleanup",
                created_at=utc_now(),
            ),
            CaseEvidence(
                case_id=case.id,
                carrier_message_id=message.id,
                field_name="client_name",
                source_type="EMAIL",
                excerpt="Different duplicate wording",
                created_at=utc_now(),
            ),
        ]
    )
    event_time = utc_now()
    candidate_time = event_time - timedelta(seconds=1)
    retained_attachment.updated_at = event_time - timedelta(seconds=20)
    duplicate_attachment.updated_at = candidate_time
    auto_dismissed = Task(
        agency_id=case.agency_id,
        case_id=case.id,
        assigned_agent_id=owner.id,
        title="Automatic duplicate",
        priority=Priority.NORMAL,
        status=TaskStatus.DISMISSED,
        updated_at=candidate_time,
    )
    historical = Task(
        agency_id=case.agency_id,
        case_id=case.id,
        assigned_agent_id=owner.id,
        title="Historically dismissed",
        priority=Priority.NORMAL,
        status=TaskStatus.DISMISSED,
        updated_at=candidate_time,
    )
    db.add_all([auto_dismissed, historical])
    db.flush()
    db.add_all(
        [
            AuditEvent(
                agency_id=case.agency_id,
                event_type="GMAIL_MAILBOX_IDENTITY_RECONCILED",
                severity=AuditSeverity.INFO,
                description="Synthetic identity reconciliation.",
                event_metadata={"connection_id": connection.id},
                created_at=event_time,
            ),
            AuditEvent(
                agency_id=case.agency_id,
                task_id=historical.id,
                event_type="TASK_STATUS_UPDATED",
                severity=AuditSeverity.INFO,
                description="Synthetic manual task history.",
                event_metadata={},
                created_at=event_time,
            ),
        ]
    )
    db.flush()

    result = reconcile_legacy_duplicate_fanout(db)
    db.flush()

    assert result.attachments_removed == 1
    assert result.evidence_removed == 1
    assert result.dismissed_tasks_removed == 1
    remaining_attachment = db.scalar(
        select(Attachment).where(Attachment.carrier_message_id == message.id)
    )
    assert remaining_attachment is not None
    assert remaining_attachment.id == retained_attachment.id
    assert remaining_attachment.processing_status is AttachmentStatus.EXTRACTED
    assert remaining_attachment.extracted_text == "Better stored extraction."
    evidence = db.scalars(
        select(CaseEvidence).where(CaseEvidence.carrier_message_id == message.id)
    ).all()
    assert [(item.field_name, item.excerpt) for item in evidence] == [
        ("client_name", "Fanout Cleanup")
    ]
    assert db.get(Task, auto_dismissed.id) is None
    assert db.get(Task, historical.id) is not None


def test_database_rejects_any_two_reviews_for_one_message(seeded_db: Session) -> None:
    db = seeded_db
    owner = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    carrier = db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    assert owner is not None and carrier is not None
    connection = GmailConnection(
        agency_id=owner.agency_id,
        user_id=owner.id,
        gmail_address="active-review-guard@gmail.test",
        status=GmailConnectionStatus.CONNECTED,
    )
    db.add(connection)
    db.flush()
    message = CarrierMessage(
        agency_id=owner.agency_id,
        carrier_id=carrier.id,
        gmail_connection_id=connection.id,
        gmail_message_id="active-review-guard",
        sender="notices@americo.test",
        subject="Active review guard",
        received_at=utc_now(),
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        raw_content="Synthetic content.",
        cleaned_content="Synthetic content.",
    )
    db.add(message)
    db.flush()

    with pytest.raises(IntegrityError), db.begin_nested():
        db.add_all(
            [
                ReviewItem(
                    agency_id=owner.agency_id,
                    carrier_message_id=message.id,
                    assigned_reviewer_id=owner.id,
                    status=ReviewStatus.RESOLVED,
                    reason_code="FIRST",
                    reason="First resolved review.",
                    resolved_at=utc_now(),
                ),
                ReviewItem(
                    agency_id=owner.agency_id,
                    carrier_message_id=message.id,
                    assigned_reviewer_id=owner.id,
                    status=ReviewStatus.IN_REVIEW,
                    reason_code="SECOND",
                    reason="Second active review.",
                ),
            ]
        )
        db.flush()


def test_review_consistency_cleanup_preserves_human_history_and_repairs_owner(
    seeded_db: Session,
) -> None:
    db = seeded_db
    owner = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    carrier = db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    assert owner is not None and carrier is not None
    db.execute(text("DROP INDEX uq_reviews_message"))
    connection = GmailConnection(
        agency_id=owner.agency_id,
        user_id=owner.id,
        gmail_address="review-consistency@gmail.test",
        status=GmailConnectionStatus.CONNECTED,
    )
    db.add(connection)
    db.flush()
    message = CarrierMessage(
        agency_id=owner.agency_id,
        carrier_id=carrier.id,
        gmail_connection_id=connection.id,
        gmail_message_id="review-consistency-message",
        sender="notices@americo.test",
        subject="Review consistency",
        received_at=utc_now(),
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        raw_content="Synthetic content.",
        cleaned_content="Synthetic content.",
    )
    distinct_message = CarrierMessage(
        agency_id=owner.agency_id,
        carrier_id=carrier.id,
        gmail_connection_id=connection.id,
        gmail_message_id="review-consistency-distinct-reply",
        gmail_thread_id="review-consistency-thread",
        sender="notices@americo.test",
        subject="Review consistency",
        received_at=utc_now(),
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        raw_content="Distinct synthetic reply.",
        cleaned_content="Distinct synthetic reply.",
    )
    message.gmail_thread_id = distinct_message.gmail_thread_id
    db.add_all([message, distinct_message])
    db.flush()
    active = ReviewItem(
        agency_id=owner.agency_id,
        carrier_message_id=message.id,
        assigned_reviewer_id=None,
        status=ReviewStatus.OPEN,
        reason_code="CURRENT",
        reason="Current actionable review",
    )
    redundant = ReviewItem(
        agency_id=owner.agency_id,
        carrier_message_id=message.id,
        assigned_reviewer_id=owner.id,
        status=ReviewStatus.DISMISSED,
        reason_code="CURRENT",
        reason="Synthetic fan-out",
        resolution_notes="Dismissed during exact Gmail message duplicate reconciliation.",
        resolved_at=utc_now(),
    )
    historical = ReviewItem(
        agency_id=owner.agency_id,
        carrier_message_id=message.id,
        assigned_reviewer_id=owner.id,
        status=ReviewStatus.RESOLVED,
        reason_code="PRIOR_CYCLE",
        reason="Prior human-reviewed cycle",
        resolution_notes="Agent confirmed the prior interpretation.",
        resolved_at=utc_now(),
    )
    distinct_review = ReviewItem(
        agency_id=owner.agency_id,
        carrier_message_id=distinct_message.id,
        assigned_reviewer_id=owner.id,
        status=ReviewStatus.OPEN,
        reason_code="DISTINCT_REPLY",
        reason="Distinct reply needs its own review",
    )
    db.add_all([active, redundant, historical, distinct_review])
    db.commit()

    consistency_result = reconcile_review_consistency(db)
    singleton_result = reconcile_single_review_per_message(db)
    db.flush()

    assert consistency_result.redundant_reviews_removed == 1
    assert consistency_result.active_reviews_reassigned == 1
    assert singleton_result.messages_reconciled == 1
    assert singleton_result.redundant_reviews_removed == 1
    assert db.get(ReviewItem, redundant.id) is None
    assert db.get(ReviewItem, historical.id) is None
    assert db.get(ReviewItem, distinct_review.id) is not None
    assert distinct_review.carrier_message_id != active.carrier_message_id
    db.refresh(active)
    assert active.assigned_reviewer_id == owner.id
