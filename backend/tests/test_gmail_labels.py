import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from httplib2 import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas.domain import TaskUpdate
from app.core.config import Settings
from app.core.time import utc_now
from app.integrations.gmail.client import GmailThreadLabelState
from app.integrations.gmail.errors import (
    GmailLabelConflict,
    GmailLabelPermanentError,
    GmailModifyPermissionRequired,
    GmailReauthorizationRequired,
    GmailTransientError,
)
from app.integrations.gmail.oauth import GMAIL_MODIFY_SCOPE, GMAIL_READONLY_SCOPE
from app.models.audit import AuditEvent
from app.models.carriers import Carrier
from app.models.enums import (
    GmailConnectionStatus,
    GmailLabelKey,
    GmailLabelSyncStatus,
    MessageClassification,
    PolicyStatus,
    Priority,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
    UserRole,
)
from app.models.gmail_labels import GmailManagedLabel, GmailThreadLabelSync
from app.models.operations import CarrierMessage, PolicyCase, ReviewItem, Task
from app.models.organization import GmailConnection, GmailOAuthCredential, User
from app.services.auth import AuthContext, create_session
from app.services.gmail_labels import (
    MANAGED_LABEL_NAMES,
    backfill_thread_label_syncs,
    claim_label_sync,
    desired_labels_for_thread,
    enqueue_for_message,
    ensure_managed_labels,
    process_claimed_label_sync,
    recover_stale_label_syncs,
    reset_connection_label_syncs,
)
from app.services.operations import update_task


class FakeLabelMailbox:
    def __init__(
        self,
        *,
        fail_modify: bool = False,
        modify_error: Exception | None = None,
    ) -> None:
        self.labels: dict[str, str] = {"Family": "user-family", "INBOX": "INBOX"}
        self.label_types: dict[str, str] = {"Family": "user", "INBOX": "system"}
        self.thread_labels: set[str] = {"user-family"}
        self.created: list[str] = []
        self.modifications: list[tuple[str, list[str], list[str]]] = []
        self.fail_modify = fail_modify
        self.modify_error = modify_error
        self.on_modify = None
        self.thread_message_labels: list[set[str]] | None = None

    def list_labels(self) -> dict:
        return {
            "labels": [
                {"name": name, "id": label_id, "type": self.label_types[name]}
                for name, label_id in self.labels.items()
            ]
        }

    def create_label(self, name: str) -> dict:
        label_id = f"managed-{len(self.created) + 1}"
        self.labels[name] = label_id
        self.label_types[name] = "user"
        self.created.append(name)
        return {"id": label_id, "name": name, "type": "user"}

    def get_thread_label_state(self, thread_id: str) -> GmailThreadLabelState:
        assert thread_id
        message_labels = self.thread_message_labels or [self.thread_labels]
        any_label_ids = set().union(*message_labels)
        all_label_ids = set(message_labels[0]).intersection(*message_labels[1:])
        return GmailThreadLabelState(
            frozenset(any_label_ids),
            frozenset(all_label_ids),
        )

    def modify_thread_labels(
        self, thread_id: str, *, add_label_ids: list[str], remove_label_ids: list[str]
    ) -> None:
        if self.fail_modify:
            raise GmailTransientError("synthetic transient")
        if self.modify_error is not None:
            raise self.modify_error
        if self.on_modify is not None:
            self.on_modify()
        self.modifications.append((thread_id, add_label_ids, remove_label_ids))
        self.thread_labels.update(add_label_ids)
        self.thread_labels.difference_update(remove_label_ids)
        for labels in self.thread_message_labels or []:
            labels.update(add_label_ids)
            labels.difference_update(remove_label_ids)


class RaisingRequest:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def execute(self) -> dict:
        raise self.error


def gmail_http_error(status: int, reason: str) -> HttpError:
    content = json.dumps(
        {
            "error": {
                "code": status,
                "status": "PERMISSION_DENIED" if status == 403 else "UNKNOWN",
                "errors": [
                    {
                        "reason": reason,
                        "message": "synthetic-sensitive-provider-detail",
                    }
                ],
                "message": "synthetic-sensitive-provider-detail",
            }
        }
    ).encode()
    return HttpError(
        Response({"status": str(status)}),
        content,
        uri="https://synthetic.invalid/provider-secret",
    )


def create_connection(
    db: Session, *, address: str, scope: str = GMAIL_MODIFY_SCOPE
) -> GmailConnection:
    owner = db.scalar(select(User).where(User.role == UserRole.AGENT).order_by(User.id))
    assert owner is not None
    connection = GmailConnection(
        agency_id=owner.agency_id,
        user_id=owner.id,
        gmail_address=address,
        status=GmailConnectionStatus.CONNECTED,
    )
    db.add(connection)
    db.flush()
    db.add(
        GmailOAuthCredential(
            gmail_connection_id=connection.id,
            encrypted_access_token="encrypted-access",
            encrypted_refresh_token="encrypted-refresh",
            granted_scopes=[scope],
        )
    )
    db.commit()
    return connection


def create_message(
    db: Session,
    connection: GmailConnection,
    *,
    thread_id: str,
    status: ProcessingStatus = ProcessingStatus.PROCESSED,
    classification: MessageClassification = MessageClassification.PENDING_REQUIREMENTS,
    received_at: datetime | None = None,
) -> CarrierMessage:
    carrier = db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    assert carrier is not None
    message = CarrierMessage(
        agency_id=connection.agency_id,
        carrier_id=carrier.id,
        gmail_connection_id=connection.id,
        gmail_message_id=f"message-{thread_id}-{utc_now().timestamp()}",
        gmail_thread_id=thread_id,
        sender="approved@example.test",
        subject="Synthetic workflow message",
        received_at=received_at or datetime(2026, 8, 20, 12, tzinfo=UTC),
        classification=(classification if status is ProcessingStatus.PROCESSED else None),
        summary=("Synthetic summary" if status is ProcessingStatus.PROCESSED else None),
        priority=(Priority.HIGH if status is ProcessingStatus.PROCESSED else None),
        processing_status=status,
        raw_content="Synthetic content",
        cleaned_content="Synthetic content",
    )
    db.add(message)
    db.commit()
    return message


def create_case_and_task(db: Session, message: CarrierMessage) -> Task:
    connection = db.get(GmailConnection, message.gmail_connection_id)
    assert connection is not None
    case = PolicyCase(
        agency_id=message.agency_id,
        carrier_id=message.carrier_id,
        assigned_agent_id=connection.user_id,
        client_name="Stage Five Test",
        policy_number=f"POLICY-{message.id}",
        current_policy_status=PolicyStatus.PENDING,
        priority=Priority.HIGH,
        summary="Synthetic case",
    )
    db.add(case)
    db.flush()
    message.case_id = case.id
    task = Task(
        agency_id=message.agency_id,
        case_id=case.id,
        source_carrier_message_id=message.id,
        source_action_index=0,
        assigned_agent_id=connection.user_id,
        title="Complete synthetic requirement",
        priority=Priority.HIGH,
        status=TaskStatus.OPEN,
    )
    db.add(task)
    db.commit()
    return task


def auth_context(db: Session, user_id: int) -> AuthContext:
    user = db.get(User, user_id)
    assert user is not None
    session, _, csrf = create_session(db, user)
    db.commit()
    return AuthContext(user=user, agency=user.agency, session=session, csrf_token=csrf)


def test_managed_labels_are_created_once_and_unrelated_labels_are_untouched(
    seeded_db: Session,
) -> None:
    connection = create_connection(seeded_db, address="labels-once@gmail.test")
    mailbox = FakeLabelMailbox()

    first = ensure_managed_labels(seeded_db, connection, mailbox)
    second = ensure_managed_labels(seeded_db, connection, mailbox)

    assert set(first) == set(GmailLabelKey)
    assert first == second
    assert mailbox.created == list(MANAGED_LABEL_NAMES.values())
    assert mailbox.labels["Family"] == "user-family"
    assert mailbox.labels["INBOX"] == "INBOX"
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(GmailManagedLabel)
            .where(GmailManagedLabel.gmail_connection_id == connection.id)
        )
        == 8
    )
    deleted_name = MANAGED_LABEL_NAMES[GmailLabelKey.FAILED]
    old_id = mailbox.labels.pop(deleted_name)
    mailbox.label_types.pop(deleted_name)
    repaired = ensure_managed_labels(seeded_db, connection, mailbox)
    assert repaired[GmailLabelKey.FAILED] != old_id
    assert mailbox.created[-1] == deleted_name


def test_concurrent_managed_label_creation_reuses_the_exact_provider_label(
    seeded_db: Session,
) -> None:
    connection = create_connection(seeded_db, address="labels-race@gmail.test")

    class RacingMailbox(FakeLabelMailbox):
        raced = False

        def create_label(self, name: str) -> dict:
            if not self.raced:
                self.raced = True
                self.labels[name] = "managed-created-by-peer"
                self.label_types[name] = "user"
                raise GmailLabelConflict("synthetic concurrent creation")
            return super().create_label(name)

    mailbox = RacingMailbox()
    bindings = ensure_managed_labels(seeded_db, connection, mailbox)

    first_key = next(iter(MANAGED_LABEL_NAMES))
    assert bindings[first_key] == "managed-created-by-peer"
    assert set(bindings) == set(GmailLabelKey)
    assert len({mailbox.labels[name] for name in MANAGED_LABEL_NAMES.values()}) == 8


@pytest.mark.parametrize(
    ("classification", "classification_label"),
    [
        (MessageClassification.POLICY_ISSUED, GmailLabelKey.POLICY_ISSUED),
        (MessageClassification.PENDING_REQUIREMENTS, GmailLabelKey.PENDING_REQUIREMENTS),
        (MessageClassification.LAPSE_NOTICE, GmailLabelKey.LAPSE_NOTICE),
        (MessageClassification.COMMISSION_UPDATE, GmailLabelKey.COMMISSION_UPDATE),
        (MessageClassification.OTHER, None),
    ],
)
def test_each_final_classification_maps_to_at_most_one_workflow_label(
    seeded_db: Session,
    classification: MessageClassification,
    classification_label: GmailLabelKey | None,
) -> None:
    connection = create_connection(
        seeded_db, address=f"mapping-{classification.value.lower()}@gmail.test"
    )
    create_message(
        seeded_db,
        connection,
        thread_id=f"thread-{classification.value.lower()}",
        classification=classification,
    )

    desired = desired_labels_for_thread(
        seeded_db,
        gmail_connection_id=connection.id,
        gmail_thread_id=f"thread-{classification.value.lower()}",
    )

    expected = {GmailLabelKey.PROCESSED}
    if classification_label is not None:
        expected.add(classification_label)
    assert desired == expected


def test_new_unfinished_message_removes_stale_thread_terminal_labels(
    seeded_db: Session,
) -> None:
    connection = create_connection(seeded_db, address="thread-state@gmail.test")
    create_message(
        seeded_db,
        connection,
        thread_id="thread-state",
        received_at=datetime(2026, 8, 20, 10, tzinfo=UTC),
    )
    create_message(
        seeded_db,
        connection,
        thread_id="thread-state",
        status=ProcessingStatus.RECEIVED,
        received_at=datetime(2026, 8, 20, 11, tzinfo=UTC),
    )

    assert (
        desired_labels_for_thread(
            seeded_db,
            gmail_connection_id=connection.id,
            gmail_thread_id="thread-state",
        )
        == set()
    )


def test_existing_gmail_thread_backfill_is_idempotent(seeded_db: Session) -> None:
    connection = create_connection(seeded_db, address="backfill@gmail.test")
    create_message(seeded_db, connection, thread_id="thread-backfill-one")
    create_message(seeded_db, connection, thread_id="thread-backfill-one")
    create_message(seeded_db, connection, thread_id="thread-backfill-two")

    assert backfill_thread_label_syncs(seeded_db) == 2
    assert backfill_thread_label_syncs(seeded_db) == 0
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(GmailThreadLabelSync)
            .where(GmailThreadLabelSync.gmail_connection_id == connection.id)
        )
        == 2
    )


def test_thread_label_rules_are_derived_from_aggregate_database_truth(
    seeded_db: Session,
) -> None:
    connection = create_connection(seeded_db, address="rules@gmail.test")
    message = create_message(seeded_db, connection, thread_id="thread-rules")
    task = create_case_and_task(seeded_db, message)

    assert desired_labels_for_thread(
        seeded_db, gmail_connection_id=connection.id, gmail_thread_id="thread-rules"
    ) == {
        GmailLabelKey.PROCESSED,
        GmailLabelKey.PENDING_REQUIREMENTS,
        GmailLabelKey.ACTION_REQUIRED,
    }

    task.status = TaskStatus.COMPLETED
    seeded_db.commit()
    assert GmailLabelKey.ACTION_REQUIRED not in desired_labels_for_thread(
        seeded_db, gmail_connection_id=connection.id, gmail_thread_id="thread-rules"
    )

    message.processing_status = ProcessingStatus.NEEDS_REVIEW
    message.classification = None
    message.summary = None
    message.priority = None
    seeded_db.add(
        ReviewItem(
            agency_id=message.agency_id,
            carrier_message_id=message.id,
            assigned_reviewer_id=connection.user_id,
            status=ReviewStatus.OPEN,
            reason_code="LOW_CONFIDENCE",
            reason="Synthetic review",
        )
    )
    seeded_db.commit()
    desired = desired_labels_for_thread(
        seeded_db, gmail_connection_id=connection.id, gmail_thread_id="thread-rules"
    )
    assert desired == {GmailLabelKey.NEEDS_REVIEW, GmailLabelKey.ACTION_REQUIRED}

    message.processing_status = ProcessingStatus.FAILED
    message.processing_next_retry_at = utc_now() + timedelta(minutes=1)
    review = seeded_db.scalar(select(ReviewItem).where(ReviewItem.carrier_message_id == message.id))
    assert review is not None
    review.status = ReviewStatus.DISMISSED
    seeded_db.commit()
    assert GmailLabelKey.FAILED not in desired_labels_for_thread(
        seeded_db, gmail_connection_id=connection.id, gmail_thread_id="thread-rules"
    )
    message.processing_next_retry_at = None
    seeded_db.commit()
    assert GmailLabelKey.FAILED in desired_labels_for_thread(
        seeded_db, gmail_connection_id=connection.id, gmail_thread_id="thread-rules"
    )


def test_label_reconciliation_is_idempotent_and_only_mutates_managed_labels(
    seeded_db: Session,
) -> None:
    connection = create_connection(seeded_db, address="apply@gmail.test")
    message = create_message(seeded_db, connection, thread_id="thread-apply")
    task = create_case_and_task(seeded_db, message)
    sync = enqueue_for_message(seeded_db, message)
    seeded_db.commit()
    assert sync is not None
    mailbox = FakeLabelMailbox()
    mailbox.labels["AI: Policy Issued"] = "managed-stale-policy"
    mailbox.label_types["AI: Policy Issued"] = "user"
    mailbox.thread_labels.update({"managed-stale-policy", "INBOX"})
    mailbox.thread_message_labels = [
        {"user-family", "INBOX"},
        {"user-family", "INBOX", "managed-stale-policy"},
    ]

    def factory(credential):
        return mailbox, False

    claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert claim is not None
    first = process_claimed_label_sync(seeded_db, claim, mailbox_factory=factory)

    assert first.status is GmailLabelSyncStatus.APPLIED
    assert len(mailbox.modifications) == 1
    assert mailbox.modifications[0][2] == ["managed-stale-policy"]
    assert "user-family" in mailbox.thread_labels
    assert "INBOX" in mailbox.thread_labels
    assert all({"user-family", "INBOX"} <= labels for labels in mailbox.thread_message_labels)
    expected_ids = {
        seeded_db.scalar(
            select(GmailManagedLabel.gmail_label_id).where(
                GmailManagedLabel.gmail_connection_id == connection.id,
                GmailManagedLabel.label_key == key,
            )
        )
        for key in {
            GmailLabelKey.PROCESSED,
            GmailLabelKey.PENDING_REQUIREMENTS,
            GmailLabelKey.ACTION_REQUIRED,
        }
    }
    assert expected_ids <= mailbox.thread_labels

    enqueue_for_message(seeded_db, message)
    seeded_db.commit()
    second_claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert second_claim is not None
    second = process_claimed_label_sync(seeded_db, second_claim, mailbox_factory=factory)
    assert second.status is GmailLabelSyncStatus.APPLIED
    assert len(mailbox.modifications) == 1

    context = auth_context(seeded_db, task.assigned_agent_id)
    update_task(
        seeded_db,
        context,
        task.id,
        TaskUpdate(status=TaskStatus.COMPLETED),
    )
    third_claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert third_claim is not None
    third = process_claimed_label_sync(seeded_db, third_claim, mailbox_factory=factory)
    action_required_id = seeded_db.scalar(
        select(GmailManagedLabel.gmail_label_id).where(
            GmailManagedLabel.gmail_connection_id == connection.id,
            GmailManagedLabel.label_key == GmailLabelKey.ACTION_REQUIRED,
        )
    )
    assert third.status is GmailLabelSyncStatus.APPLIED
    assert mailbox.modifications[-1][2] == [action_required_id]
    assert expected_ids - {action_required_id} <= mailbox.thread_labels


def test_reconciliation_adds_desired_labels_missing_from_a_new_thread_message(
    seeded_db: Session,
) -> None:
    connection = create_connection(seeded_db, address="thread-completeness@gmail.test")
    first_message = create_message(seeded_db, connection, thread_id="thread-completeness")
    sync = enqueue_for_message(seeded_db, first_message)
    seeded_db.commit()
    assert sync is not None
    mailbox = FakeLabelMailbox()

    first_claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert first_claim is not None
    first = process_claimed_label_sync(
        seeded_db,
        first_claim,
        mailbox_factory=lambda credential: (mailbox, False),
    )
    assert first.status is GmailLabelSyncStatus.APPLIED
    desired_ids = set(mailbox.thread_labels) - {"user-family"}

    mailbox.thread_message_labels = [set(mailbox.thread_labels), {"user-family"}]
    second_message = create_message(
        seeded_db,
        connection,
        thread_id="thread-completeness",
        received_at=datetime(2026, 8, 20, 13, tzinfo=UTC),
    )
    enqueue_for_message(seeded_db, second_message)
    seeded_db.commit()
    second_claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert second_claim is not None
    second = process_claimed_label_sync(
        seeded_db,
        second_claim,
        mailbox_factory=lambda credential: (mailbox, False),
    )

    assert second.status is GmailLabelSyncStatus.APPLIED
    assert set(mailbox.modifications[-1][1]) == desired_ids
    assert mailbox.modifications[-1][2] == []
    assert all(desired_ids <= labels for labels in mailbox.thread_message_labels)
    assert all("user-family" in labels for labels in mailbox.thread_message_labels)


def test_all_draft_thread_does_not_trigger_an_impossible_label_update(
    seeded_db: Session,
) -> None:
    class AllDraftMailbox(FakeLabelMailbox):
        def get_thread_label_state(self, thread_id: str) -> GmailThreadLabelState:
            return GmailThreadLabelState(frozenset(), frozenset(), 0)

    connection = create_connection(seeded_db, address="all-draft@gmail.test")
    message = create_message(seeded_db, connection, thread_id="thread-all-draft")
    sync = enqueue_for_message(seeded_db, message)
    seeded_db.commit()
    assert sync is not None
    claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert claim is not None
    mailbox = AllDraftMailbox()

    result = process_claimed_label_sync(
        seeded_db,
        claim,
        mailbox_factory=lambda credential: (mailbox, False),
    )

    assert result.status is GmailLabelSyncStatus.APPLIED
    assert mailbox.modifications == []


def test_label_failure_retries_without_changing_processed_message(
    seeded_db: Session,
) -> None:
    connection = create_connection(seeded_db, address="retry@gmail.test")
    message = create_message(seeded_db, connection, thread_id="thread-retry")
    sync = enqueue_for_message(seeded_db, message)
    seeded_db.commit()
    assert sync is not None
    mailbox = FakeLabelMailbox(fail_modify=True)
    settings = Settings(
        gmail_label_max_attempts=2,
        gmail_label_retry_base_seconds=1,
        gmail_label_retry_max_seconds=2,
    )

    claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert claim is not None
    failed = process_claimed_label_sync(
        seeded_db,
        claim,
        settings=settings,
        mailbox_factory=lambda credential: (mailbox, False),
    )

    seeded_db.refresh(message)
    assert failed.status is GmailLabelSyncStatus.RETRY_WAIT
    assert message.processing_status is ProcessingStatus.PROCESSED
    sync = seeded_db.get(GmailThreadLabelSync, sync.id)
    assert sync is not None and sync.next_retry_at is not None
    sync.next_retry_at = utc_now() - timedelta(seconds=1)
    seeded_db.commit()
    mailbox.fail_modify = False
    retry_claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert retry_claim is not None
    applied = process_claimed_label_sync(
        seeded_db,
        retry_claim,
        settings=settings,
        mailbox_factory=lambda credential: (mailbox, False),
    )
    assert applied.status is GmailLabelSyncStatus.APPLIED


def test_exhausted_label_failure_does_not_block_another_connection(
    seeded_db: Session,
) -> None:
    failing_connection = create_connection(seeded_db, address="labels-failing@gmail.test")
    healthy_connection = create_connection(seeded_db, address="labels-healthy@gmail.test")
    failing_message = create_message(
        seeded_db, failing_connection, thread_id="thread-label-failing"
    )
    healthy_message = create_message(
        seeded_db, healthy_connection, thread_id="thread-label-healthy"
    )
    failing_sync = enqueue_for_message(seeded_db, failing_message)
    healthy_sync = enqueue_for_message(seeded_db, healthy_message)
    seeded_db.commit()
    assert failing_sync is not None and healthy_sync is not None
    settings = Settings(gmail_label_max_attempts=1)

    failing_claim = claim_label_sync(seeded_db, sync_id=failing_sync.id)
    assert failing_claim is not None
    exhausted = process_claimed_label_sync(
        seeded_db,
        failing_claim,
        settings=settings,
        mailbox_factory=lambda credential: (FakeLabelMailbox(fail_modify=True), False),
    )
    healthy_claim = claim_label_sync(seeded_db, sync_id=healthy_sync.id)
    assert healthy_claim is not None
    applied = process_claimed_label_sync(
        seeded_db,
        healthy_claim,
        settings=settings,
        mailbox_factory=lambda credential: (FakeLabelMailbox(), False),
    )

    assert exhausted.status is GmailLabelSyncStatus.FAILED
    assert applied.status is GmailLabelSyncStatus.APPLIED
    seeded_db.refresh(failing_message)
    seeded_db.refresh(healthy_message)
    assert failing_message.processing_status is ProcessingStatus.PROCESSED
    assert healthy_message.processing_status is ProcessingStatus.PROCESSED


def test_stale_success_cannot_mutate_a_newer_claimed_generation(
    seeded_db: Session,
) -> None:
    connection = create_connection(seeded_db, address="generation@gmail.test")
    message = create_message(seeded_db, connection, thread_id="thread-generation")
    sync = enqueue_for_message(seeded_db, message)
    seeded_db.commit()
    assert sync is not None
    mailbox = FakeLabelMailbox()
    claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert claim is not None
    newer_claims = []

    def claim_newer_generation() -> None:
        enqueue_for_message(seeded_db, message)
        seeded_db.commit()
        newer_claim = claim_label_sync(seeded_db, sync_id=sync.id)
        assert newer_claim is not None
        newer_claims.append(newer_claim)

    mailbox.on_modify = claim_newer_generation
    result = process_claimed_label_sync(
        seeded_db,
        claim,
        mailbox_factory=lambda credential: (mailbox, False),
    )

    assert len(newer_claims) == 1
    newer_claim = newer_claims[0]
    assert result.status is GmailLabelSyncStatus.PROCESSING
    current = seeded_db.get(GmailThreadLabelSync, sync.id)
    assert current is not None
    assert current.generation == newer_claim.generation == claim.generation + 1
    assert current.status is GmailLabelSyncStatus.PROCESSING
    assert current.claimed_generation == newer_claim.generation
    assert current.processing_started_at is not None
    assert current.attempt_count == 1
    assert current.applied_label_keys == []
    assert current.last_applied_at is None
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.agency_id == connection.agency_id,
                AuditEvent.event_type == "GMAIL_WORKFLOW_LABELS_APPLIED",
            )
        )
        == 0
    )

    mailbox.on_modify = None
    applied = process_claimed_label_sync(
        seeded_db,
        newer_claim,
        mailbox_factory=lambda credential: (mailbox, False),
    )
    seeded_db.refresh(current)
    assert applied.status is GmailLabelSyncStatus.APPLIED
    assert current.status is GmailLabelSyncStatus.APPLIED
    assert current.claimed_generation is None
    assert current.last_applied_at is not None


@pytest.mark.parametrize(
    "provider_error",
    [
        GmailTransientError("synthetic transient"),
        GmailLabelPermanentError("synthetic permanent"),
        GmailModifyPermissionRequired("synthetic permission"),
    ],
)
def test_stale_label_failure_cannot_overwrite_a_newer_generation(
    seeded_db: Session,
    provider_error: Exception,
) -> None:
    connection = create_connection(seeded_db, address=f"stale-{type(provider_error).__name__}@test")
    message = create_message(seeded_db, connection, thread_id="thread-stale-failure")
    sync = enqueue_for_message(seeded_db, message)
    seeded_db.commit()
    assert sync is not None
    mailbox = FakeLabelMailbox()
    claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert claim is not None

    def enqueue_newer_work_then_fail() -> None:
        enqueue_for_message(seeded_db, message)
        seeded_db.commit()
        raise provider_error

    mailbox.on_modify = enqueue_newer_work_then_fail
    result = process_claimed_label_sync(
        seeded_db,
        claim,
        settings=Settings(gmail_label_max_attempts=1),
        mailbox_factory=lambda credential: (mailbox, False),
    )

    current = seeded_db.get(GmailThreadLabelSync, sync.id)
    assert current is not None
    assert result.status is GmailLabelSyncStatus.PENDING
    assert current.generation == claim.generation + 1
    assert current.status is GmailLabelSyncStatus.PENDING
    assert current.attempt_count == 0
    assert current.claimed_generation is None
    assert current.next_retry_at is None
    assert current.last_error_code is None
    failure_events = seeded_db.scalars(
        select(AuditEvent.event_type).where(
            AuditEvent.agency_id == connection.agency_id,
            AuditEvent.event_type.in_(
                [
                    "GMAIL_LABEL_PERMISSION_REQUIRED",
                    "GMAIL_LABEL_RETRY_EXHAUSTED",
                    "GMAIL_LABEL_RETRY_SCHEDULED",
                ]
            ),
        )
    ).all()
    assert failure_events == []


def test_stale_recovery_fences_old_success_and_new_claim_converges(
    seeded_db: Session,
) -> None:
    connection = create_connection(seeded_db, address="stale-recovery-success@test")
    message = create_message(seeded_db, connection, thread_id="thread-stale-recovery-success")
    sync = enqueue_for_message(seeded_db, message)
    seeded_db.commit()
    assert sync is not None
    old_claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert old_claim is not None
    sync.processing_started_at = utc_now() - timedelta(minutes=10)
    seeded_db.commit()

    recovered = recover_stale_label_syncs(
        seeded_db,
        settings=Settings(gmail_label_stale_after_seconds=60),
    )
    seeded_db.refresh(sync)
    assert recovered == 1
    assert sync.generation == old_claim.generation + 1
    assert sync.status is GmailLabelSyncStatus.PENDING
    assert sync.attempt_count == 1
    assert sync.last_error_code == "GMAIL_LABEL_STALE_RECOVERED"

    mailbox = FakeLabelMailbox()
    old_result = process_claimed_label_sync(
        seeded_db,
        old_claim,
        mailbox_factory=lambda credential: (mailbox, False),
    )
    seeded_db.refresh(sync)
    assert old_result.status is GmailLabelSyncStatus.PENDING
    assert sync.status is GmailLabelSyncStatus.PENDING
    assert sync.attempt_count == 1
    assert sync.last_error_code == "GMAIL_LABEL_STALE_RECOVERED"

    recovered_claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert recovered_claim is not None
    assert recovered_claim.generation == old_claim.generation + 1
    applied = process_claimed_label_sync(
        seeded_db,
        recovered_claim,
        mailbox_factory=lambda credential: (mailbox, False),
    )
    seeded_db.refresh(sync)
    assert applied.status is GmailLabelSyncStatus.APPLIED
    assert sync.status is GmailLabelSyncStatus.APPLIED
    assert sync.attempt_count == 2
    assert sync.last_error_code is None


@pytest.mark.parametrize(
    "provider_error",
    [
        GmailTransientError("synthetic transient"),
        GmailLabelPermanentError("synthetic permanent"),
        GmailModifyPermissionRequired("synthetic permission"),
    ],
)
def test_stale_recovery_fences_every_old_failure_class(
    seeded_db: Session,
    provider_error: Exception,
) -> None:
    connection = create_connection(
        seeded_db,
        address=f"recovered-{type(provider_error).__name__}@test",
    )
    message = create_message(seeded_db, connection, thread_id="thread-recovered-failure")
    sync = enqueue_for_message(seeded_db, message)
    seeded_db.commit()
    assert sync is not None
    old_claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert old_claim is not None
    sync.processing_started_at = utc_now() - timedelta(minutes=10)
    seeded_db.commit()
    recover_stale_label_syncs(
        seeded_db,
        settings=Settings(gmail_label_stale_after_seconds=60),
    )

    old_result = process_claimed_label_sync(
        seeded_db,
        old_claim,
        settings=Settings(gmail_label_max_attempts=1),
        mailbox_factory=lambda credential: (
            FakeLabelMailbox(modify_error=provider_error),
            False,
        ),
    )

    current = seeded_db.get(GmailThreadLabelSync, sync.id)
    assert current is not None
    assert old_result.status is GmailLabelSyncStatus.PENDING
    assert current.generation == old_claim.generation + 1
    assert current.status is GmailLabelSyncStatus.PENDING
    assert current.attempt_count == 1
    assert current.claimed_generation is None
    assert current.next_retry_at is None
    assert current.last_error_code == "GMAIL_LABEL_STALE_RECOVERED"


def test_readonly_connection_blocks_label_provider_call_until_scope_upgrade(
    seeded_db: Session,
) -> None:
    connection = create_connection(
        seeded_db, address="readonly@gmail.test", scope=GMAIL_READONLY_SCOPE
    )
    message = create_message(seeded_db, connection, thread_id="thread-readonly")
    sync = enqueue_for_message(seeded_db, message)
    seeded_db.commit()
    assert sync is not None
    calls = 0

    def factory(credential):
        nonlocal calls
        calls += 1
        return FakeLabelMailbox(), False

    claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert claim is not None
    blocked = process_claimed_label_sync(seeded_db, claim, mailbox_factory=factory)
    assert blocked.status is GmailLabelSyncStatus.NEEDS_PERMISSION
    assert calls == 0

    credential = connection.oauth_credential
    assert credential is not None
    credential.granted_scopes = [GMAIL_MODIFY_SCOPE]
    seeded_db.commit()
    reset_connection_label_syncs(seeded_db, connection.id)
    upgraded_claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert upgraded_claim is not None
    upgraded = process_claimed_label_sync(seeded_db, upgraded_claim, mailbox_factory=factory)
    assert upgraded.status is GmailLabelSyncStatus.APPLIED
    assert calls == 1


def test_stale_label_work_is_recovered_and_task_change_dirties_thread(
    seeded_db: Session,
) -> None:
    connection = create_connection(seeded_db, address="stale@gmail.test")
    message = create_message(seeded_db, connection, thread_id="thread-stale")
    task = create_case_and_task(seeded_db, message)
    sync = enqueue_for_message(seeded_db, message)
    seeded_db.commit()
    assert sync is not None
    sync.status = GmailLabelSyncStatus.PROCESSING
    sync.processing_started_at = utc_now() - timedelta(minutes=10)
    seeded_db.commit()

    recovered = recover_stale_label_syncs(
        seeded_db, settings=Settings(gmail_label_stale_after_seconds=60)
    )
    assert recovered == 1
    seeded_db.refresh(sync)
    starting_generation = sync.generation
    context = auth_context(seeded_db, task.assigned_agent_id)
    update_task(
        seeded_db,
        context,
        task.id,
        TaskUpdate(status=TaskStatus.COMPLETED),
    )
    seeded_db.refresh(sync)
    assert sync.status is GmailLabelSyncStatus.PENDING
    assert sync.generation == starting_generation + 1


def test_google_mailbox_rejects_modify_without_scope_before_service_access() -> None:
    from app.integrations.gmail.client import GoogleGmailMailbox

    mailbox = GoogleGmailMailbox.__new__(GoogleGmailMailbox)
    mailbox._can_modify = False
    mailbox._service = None

    with pytest.raises(GmailModifyPermissionRequired):
        mailbox.list_labels()


@pytest.mark.parametrize(
    ("status", "reason", "expected_error"),
    [
        (403, "rateLimitExceeded", GmailTransientError),
        (403, "userRateLimitExceeded", GmailTransientError),
        (403, "insufficientPermissions", GmailModifyPermissionRequired),
        (403, "domainPolicy", GmailLabelPermanentError),
        (403, "dailyLimitExceeded", GmailLabelPermanentError),
        (403, "unknownProviderRestriction", GmailLabelPermanentError),
        (429, "rateLimitExceeded", GmailTransientError),
        (500, "backendError", GmailTransientError),
        (503, "backendError", GmailTransientError),
        (401, "authError", GmailReauthorizationRequired),
    ],
)
def test_google_mailbox_classifies_label_http_errors_by_status_and_safe_reason(
    status: int,
    reason: str,
    expected_error: type[Exception],
) -> None:
    from app.integrations.gmail.client import GoogleGmailMailbox

    with pytest.raises(expected_error) as raised:
        GoogleGmailMailbox._execute_label(RaisingRequest(gmail_http_error(status, reason)))

    assert "sensitive" not in str(raised.value).lower()
    assert "provider-secret" not in str(raised.value).lower()


@pytest.mark.parametrize("reason", ["rateLimitExceeded", "userRateLimitExceeded"])
def test_label_rate_limit_uses_safe_bounded_retry_without_provider_detail(
    seeded_db: Session,
    reason: str,
) -> None:
    from app.integrations.gmail.client import GoogleGmailMailbox

    class RateLimitedMailbox(FakeLabelMailbox):
        def modify_thread_labels(
            self,
            thread_id: str,
            *,
            add_label_ids: list[str],
            remove_label_ids: list[str],
        ) -> None:
            GoogleGmailMailbox._execute_label(RaisingRequest(gmail_http_error(403, reason)))

    connection = create_connection(seeded_db, address=f"{reason.lower()}@test")
    message = create_message(seeded_db, connection, thread_id=f"thread-{reason}")
    sync = enqueue_for_message(seeded_db, message)
    seeded_db.commit()
    assert sync is not None
    claim = claim_label_sync(seeded_db, sync_id=sync.id)
    assert claim is not None

    result = process_claimed_label_sync(
        seeded_db,
        claim,
        settings=Settings(
            gmail_label_max_attempts=3,
            gmail_label_retry_base_seconds=1,
        ),
        mailbox_factory=lambda credential: (RateLimitedMailbox(), False),
    )

    current = seeded_db.get(GmailThreadLabelSync, sync.id)
    assert current is not None
    assert result.status is GmailLabelSyncStatus.RETRY_WAIT
    assert current.status is GmailLabelSyncStatus.RETRY_WAIT
    assert current.next_retry_at is not None
    assert current.last_error_code == "GMAIL_THREAD_LABEL_FAILED"
    event = seeded_db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.agency_id == connection.agency_id,
            AuditEvent.event_type == "GMAIL_LABEL_RETRY_SCHEDULED",
        )
        .order_by(AuditEvent.id.desc())
    )
    assert event is not None
    persisted = f"{event.description} {event.event_metadata} {current.last_error_code}"
    assert "sensitive" not in persisted.lower()
    assert "provider-secret" not in persisted.lower()


@pytest.mark.parametrize("execute_label", [False, True])
def test_refresh_error_during_request_execution_requires_reauthorization(
    execute_label: bool,
) -> None:
    from app.integrations.gmail.client import GoogleGmailMailbox

    request = RaisingRequest(RefreshError("synthetic-sensitive-refresh-detail"))
    executor = GoogleGmailMailbox._execute_label if execute_label else GoogleGmailMailbox._execute

    with pytest.raises(GmailReauthorizationRequired) as raised:
        executor(request)

    assert "sensitive" not in str(raised.value).lower()


def test_google_mailbox_exposes_only_expected_label_and_thread_operations() -> None:
    from app.integrations.gmail.client import GoogleGmailMailbox

    calls: list[tuple[str, dict]] = []

    class Request:
        def __init__(self, response: dict) -> None:
            self.response = response

        def execute(self) -> dict:
            return self.response

    class Labels:
        def list(self, **kwargs):
            calls.append(("labels.list", kwargs))
            return Request({"labels": []})

        def create(self, **kwargs):
            calls.append(("labels.create", kwargs))
            return Request({"id": "managed-1"})

    class Threads:
        def get(self, **kwargs):
            calls.append(("threads.get", kwargs))
            return Request(
                {
                    "messages": [
                        {"labelIds": ["managed-1", "INBOX"]},
                        {"labelIds": ["INBOX"]},
                    ]
                }
            )

        def modify(self, **kwargs):
            calls.append(("threads.modify", kwargs))
            return Request({"id": kwargs["id"]})

    mailbox = GoogleGmailMailbox.__new__(GoogleGmailMailbox)
    mailbox._can_modify = True
    mailbox._service = SimpleNamespace(
        users=lambda: SimpleNamespace(labels=lambda: Labels(), threads=lambda: Threads())
    )

    assert mailbox.list_labels() == {"labels": []}
    assert mailbox.create_label("Processed")["id"] == "managed-1"
    thread_state = mailbox.get_thread_label_state("thread-1")
    assert thread_state.any_label_ids == {"managed-1", "INBOX"}
    assert thread_state.all_label_ids == {"INBOX"}
    assert thread_state.labelable_message_count == 2
    mailbox.modify_thread_labels("thread-1", add_label_ids=["managed-1"], remove_label_ids=[])

    assert calls[0] == ("labels.list", {"userId": "me"})
    assert calls[1][0] == "labels.create"
    assert calls[1][1]["body"]["name"] == "Processed"
    assert calls[2] == (
        "threads.get",
        {"userId": "me", "id": "thread-1", "format": "minimal"},
    )
    assert calls[3] == (
        "threads.modify",
        {
            "userId": "me",
            "id": "thread-1",
            "body": {"addLabelIds": ["managed-1"], "removeLabelIds": []},
        },
    )


def test_google_mailbox_excludes_drafts_from_thread_label_completeness() -> None:
    from app.integrations.gmail.client import GoogleGmailMailbox

    class Request:
        def execute(self) -> dict:
            return {
                "messages": [
                    {"labelIds": ["managed-1", "INBOX"]},
                    {"labelIds": ["DRAFT"]},
                ]
            }

    mailbox = GoogleGmailMailbox.__new__(GoogleGmailMailbox)
    mailbox._can_modify = True
    mailbox._service = SimpleNamespace(
        users=lambda: SimpleNamespace(
            threads=lambda: SimpleNamespace(get=lambda **kwargs: Request())
        )
    )

    state = mailbox.get_thread_label_state("thread-with-draft")

    assert state.any_label_ids == {"managed-1", "INBOX"}
    assert state.all_label_ids == {"managed-1", "INBOX"}
    assert state.labelable_message_count == 1


def test_google_mailbox_reports_an_all_draft_thread_without_labelable_messages() -> None:
    from app.integrations.gmail.client import GoogleGmailMailbox

    class Request:
        def execute(self) -> dict:
            return {"messages": [{"labelIds": ["DRAFT"]}]}

    mailbox = GoogleGmailMailbox.__new__(GoogleGmailMailbox)
    mailbox._can_modify = True
    mailbox._service = SimpleNamespace(
        users=lambda: SimpleNamespace(
            threads=lambda: SimpleNamespace(get=lambda **kwargs: Request())
        )
    )

    state = mailbox.get_thread_label_state("all-draft-thread")

    assert state.any_label_ids == set()
    assert state.all_label_ids == set()
    assert state.labelable_message_count == 0


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"messages": None},
        {"messages": "malformed"},
        {"messages": []},
        {"messages": [None, {"labelIds": "malformed"}]},
    ],
)
def test_google_mailbox_rejects_empty_or_malformed_thread_labels(response: dict) -> None:
    from app.integrations.gmail.client import GoogleGmailMailbox

    class Request:
        def execute(self) -> dict:
            return response

    mailbox = GoogleGmailMailbox.__new__(GoogleGmailMailbox)
    mailbox._can_modify = True
    mailbox._service = SimpleNamespace(
        users=lambda: SimpleNamespace(
            threads=lambda: SimpleNamespace(get=lambda **kwargs: Request())
        )
    )

    with pytest.raises(GmailTransientError):
        mailbox.get_thread_label_state("thread-malformed")


def test_message_label_reconciliation_is_semantic_csrf_protected_and_scoped(
    client: TestClient, seeded_db: Session, login
) -> None:
    connection = create_connection(seeded_db, address="label-api@gmail.test")
    message = create_message(seeded_db, connection, thread_id="thread-label-api")
    enqueue_for_message(seeded_db, message)
    seeded_db.commit()

    owner = login(client, "agent.one@demo.local")
    assert (
        client.post(f"/api/v1/carrier-messages/{message.id}/reconcile-gmail-labels").status_code
        == 403
    )
    other = login(client, "agent.two@demo.local")
    hidden = client.post(
        f"/api/v1/carrier-messages/{message.id}/reconcile-gmail-labels",
        headers={"X-CSRF-Token": other["csrf_token"]},
    )
    assert hidden.status_code == 404
    owner = login(client, "agent.one@demo.local")
    queued = client.post(
        f"/api/v1/carrier-messages/{message.id}/reconcile-gmail-labels",
        headers={"X-CSRF-Token": owner["csrf_token"]},
    )
    assert queued.status_code == 200
