import base64
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.ai.schemas import ActionItem, AnalysisResult, Deadline, Evidence
from app.integrations.gmail.client import GmailThreadLabelState
from app.integrations.gmail.errors import GmailTransientError
from app.integrations.gmail.oauth import GMAIL_MODIFY_SCOPE
from app.integrations.gmail.sync import sync_connection
from app.models.enums import (
    GmailConnectionStatus,
    GmailLabelSyncStatus,
    MessageClassification,
    PolicyStatus,
    Priority,
    ProcessingStatus,
    UserRole,
)
from app.models.gmail_labels import GmailThreadLabelSync
from app.models.operations import CarrierMessage, CaseEvidence, PolicyCase, ReviewItem, Task
from app.models.organization import GmailConnection, GmailOAuthCredential, User
from app.services.gmail_labels import claim_label_sync, process_claimed_label_sync
from app.services.message_processing import claim_message, process_claimed_message
from app.workers.pipeline import pipeline_once


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def gmail_message(message_id: str, sender: str, body: str) -> dict[str, Any]:
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "internalDate": "1787184000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": f"Synthetic Sender <{sender}>"},
                {"name": "Subject", "value": "Stage 5 offline pipeline"},
            ],
            "body": {"data": encoded(body)},
        },
    }


class PipelineMailbox:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = {item["id"]: item for item in messages}
        self.full_fetches: list[str] = []
        self.labels: dict[str, str] = {}
        self.thread_labels: dict[str, set[str]] = {}
        self.modify_calls: list[str] = []
        self.fail_modify = False

    def list_messages(self, query: str, page_token: str | None = None) -> dict:
        assert page_token is None
        return {"messages": [{"id": message_id} for message_id in self.messages]}

    def get_metadata(self, message_id: str) -> dict:
        message = self.messages[message_id]
        return {"id": message_id, "payload": {"headers": message["payload"]["headers"]}}

    def get_full_message(self, message_id: str) -> dict:
        self.full_fetches.append(message_id)
        return self.messages[message_id]

    def list_labels(self) -> dict:
        return {
            "labels": [
                {"name": name, "id": label_id, "type": "user"}
                for name, label_id in self.labels.items()
            ]
        }

    def create_label(self, name: str) -> dict:
        label_id = f"label-{len(self.labels) + 1}"
        self.labels[name] = label_id
        return {"id": label_id, "name": name, "type": "user"}

    def get_thread_label_state(self, thread_id: str) -> GmailThreadLabelState:
        labels = frozenset(self.thread_labels.get(thread_id, set()))
        return GmailThreadLabelState(labels, labels)

    def modify_thread_labels(
        self, thread_id: str, *, add_label_ids: list[str], remove_label_ids: list[str]
    ) -> None:
        if self.fail_modify:
            raise GmailTransientError("synthetic label outage")
        self.modify_calls.append(thread_id)
        labels = self.thread_labels.setdefault(thread_id, set())
        labels.update(add_label_ids)
        labels.difference_update(remove_label_ids)


class FakeAnalyzer:
    model_name = "synthetic-stage5-model"

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, source_bundle: str) -> AnalysisResult:
        self.calls += 1
        assert "Stage Five Offline" in source_bundle
        return AnalysisResult(
            classification=MessageClassification.PENDING_REQUIREMENTS,
            summary="Americo needs a signed authorization for Stage Five Offline.",
            priority=Priority.HIGH,
            client_name="Stage Five Offline",
            policy_number="OFFLINE-5001",
            policy_status=PolicyStatus.PENDING,
            premium_amount=None,
            currency=None,
            effective_date=None,
            deadline=Deadline(
                raw_text="by August 28, 2026",
                explicit_date="2026-08-28",
                relative_count=None,
                relative_unit=None,
            ),
            requirements=["Signed authorization form"],
            action_items=[
                ActionItem(
                    title="Obtain signed authorization",
                    description="Submit the signed authorization to Americo.",
                    priority=Priority.HIGH,
                    explicit_due_date="2026-08-28",
                    due_text="by August 28, 2026",
                )
            ],
            evidence=[
                Evidence(
                    field_name="client_name",
                    source_id="email",
                    excerpt="Client Name: Stage Five Offline",
                ),
                Evidence(
                    field_name="policy_number",
                    source_id="email",
                    excerpt="Policy Number: OFFLINE-5001",
                ),
                Evidence(
                    field_name="policy_status",
                    source_id="email",
                    excerpt="Policy Status: PENDING",
                ),
                Evidence(
                    field_name="deadline",
                    source_id="email",
                    excerpt="by August 28, 2026",
                ),
                Evidence(
                    field_name="action_item:0",
                    source_id="email",
                    excerpt="Obtain the signed authorization form",
                ),
            ],
            overall_confidence=0.95,
            uncertainties=[],
        )


def test_offline_pipeline_is_automatic_idempotent_and_whitelist_first(
    seeded_db: Session,
) -> None:
    owner = seeded_db.scalar(select(User).where(User.role == UserRole.AGENT).order_by(User.id))
    assert owner is not None
    connection = GmailConnection(
        agency_id=owner.agency_id,
        user_id=owner.id,
        gmail_address="pipeline@gmail.test",
        status=GmailConnectionStatus.CONNECTED,
    )
    seeded_db.add(connection)
    seeded_db.flush()
    seeded_db.add(
        GmailOAuthCredential(
            gmail_connection_id=connection.id,
            encrypted_access_token="encrypted-access",
            encrypted_refresh_token="encrypted-refresh",
            granted_scopes=[GMAIL_MODIFY_SCOPE],
        )
    )
    seeded_db.commit()
    body = (
        "Client Name: Stage Five Offline\n"
        "Policy Number: OFFLINE-5001\n"
        "Policy Status: PENDING\n"
        "Obtain the signed authorization form and submit it to Americo by August 28, 2026."
    )
    mailbox = PipelineMailbox(
        [
            gmail_message("approved-5001", "alerts@americo.com", body),
            gmail_message("unapproved-5001", "friend@example.test", "Never persist this body"),
        ]
    )
    analyzer = FakeAnalyzer()
    mailbox.fail_modify = True
    initial_counts = {
        model: seeded_db.scalar(select(func.count()).select_from(model)) or 0
        for model in (CarrierMessage, PolicyCase, Task, CaseEvidence, ReviewItem)
    }

    def poll():
        return [
            sync_connection(
                seeded_db,
                connection.id,
                mailbox_factory=lambda credential: (mailbox, False),
            )
        ]

    def process():
        claimed = claim_message(seeded_db)
        if claimed is None:
            return []
        return [
            process_claimed_message(
                seeded_db,
                claimed,
                analyzer=analyzer,
            )
        ]

    def labels():
        results = []
        while (claim := claim_label_sync(seeded_db)) is not None:
            results.append(
                process_claimed_label_sync(
                    seeded_db,
                    claim,
                    mailbox_factory=lambda credential: (mailbox, False),
                )
            )
        return results

    first = pipeline_once(
        poll_function=poll,
        process_function=process,
        label_function=labels,
    )
    stored = seeded_db.scalar(
        select(CarrierMessage).where(CarrierMessage.gmail_message_id == "approved-5001")
    )
    assert stored is not None
    assert first.messages_ingested == first.messages_processed == 1
    assert stored.processing_status is ProcessingStatus.PROCESSED
    assert stored.case is not None
    assert stored.case.current_deadline is not None
    assert (
        stored.case.current_deadline.astimezone(ZoneInfo("America/Chicago")).date().isoformat()
        == "2026-08-28"
    )
    created_task = seeded_db.scalar(select(Task).where(Task.source_carrier_message_id == stored.id))
    assert created_task is not None and created_task.due_at is not None
    assert (
        created_task.due_at.astimezone(ZoneInfo("America/Chicago")).date().isoformat()
        == "2026-08-28"
    )
    assert analyzer.calls == 1
    assert mailbox.full_fetches == ["approved-5001"]
    assert not seeded_db.scalars(
        select(CarrierMessage).where(CarrierMessage.raw_content.contains("Never persist"))
    ).all()
    sync = seeded_db.scalar(
        select(GmailThreadLabelSync).where(
            GmailThreadLabelSync.gmail_connection_id == connection.id,
            GmailThreadLabelSync.gmail_thread_id == stored.gmail_thread_id,
        )
    )
    assert sync is not None and sync.status is GmailLabelSyncStatus.RETRY_WAIT
    first_counts = {
        model: seeded_db.scalar(select(func.count()).select_from(model)) or 0
        for model in initial_counts
    }

    sync.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
    seeded_db.commit()
    mailbox.fail_modify = False
    second = pipeline_once(
        poll_function=poll,
        process_function=process,
        label_function=labels,
    )
    second_counts = {
        model: seeded_db.scalar(select(func.count()).select_from(model)) or 0
        for model in initial_counts
    }
    assert second.messages_ingested == second.messages_processed == 0
    assert analyzer.calls == 1
    assert second_counts == first_counts
    seeded_db.refresh(sync)
    assert sync.status is GmailLabelSyncStatus.APPLIED
    assert first_counts[CarrierMessage] == initial_counts[CarrierMessage] + 1
    assert first_counts[PolicyCase] == initial_counts[PolicyCase] + 1
    assert first_counts[Task] == initial_counts[Task] + 1
    assert first_counts[CaseEvidence] == initial_counts[CaseEvidence] + 5
    assert first_counts[ReviewItem] == initial_counts[ReviewItem]
