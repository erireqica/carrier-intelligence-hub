import base64
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.time import utc_now
from app.db.seed import seed_demo_data
from app.integrations.gmail.errors import (
    GmailReauthorizationRequired,
    GmailTransientError,
)
from app.integrations.gmail.sync import (
    SyncResult,
    backfill_observed_messages,
    sync_connection,
)
from app.models.audit import AuditEvent
from app.models.carriers import Carrier
from app.models.enums import GmailConnectionStatus, ProcessingStatus
from app.models.operations import Attachment, CarrierMessage
from app.models.organization import (
    GmailConnection,
    GmailOAuthCredential,
    GmailObservedMessage,
    User,
)
from app.workers.gmail_poll import _configure_shutdown_signals, poll_once


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def gmail_message(
    message_id: str,
    sender: str,
    *,
    subject: str = "Pending requirements for policy TEST-10001",
    body: str = "Synthetic development message.",
    attachment: bool = False,
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [
        {"partId": "0", "mimeType": "text/plain", "body": {"data": encoded(body)}}
    ]
    if attachment:
        parts.append(
            {
                "partId": "1",
                "mimeType": "application/pdf",
                "filename": "synthetic-requirements.pdf",
                "body": {"attachmentId": f"attachment-{message_id}", "size": 2048},
            }
        )
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "internalDate": "1787184000000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": f"Synthetic Sender <{sender}>"},
                {"name": "Subject", "value": subject},
            ],
            "parts": parts,
        },
    }


class FakeMailbox:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = {item["id"]: item for item in messages}
        self.full_fetches: list[str] = []
        self.list_calls: list[str | None] = []

    def list_messages(self, query: str, page_token: str | None = None) -> dict:
        assert query.startswith("in:inbox is:unread newer_than:")
        self.list_calls.append(page_token)
        ids = list(self.messages)
        if len(ids) > 1 and page_token is None:
            return {"messages": [{"id": ids[0]}], "nextPageToken": "next"}
        selected = ids[1:] if page_token else ids
        return {"messages": [{"id": item} for item in selected]}

    def get_metadata(self, message_id: str) -> dict:
        full = self.messages[message_id]
        return {"id": message_id, "payload": {"headers": full["payload"]["headers"]}}

    def get_full_message(self, message_id: str) -> dict:
        self.full_fetches.append(message_id)
        return self.messages[message_id]


def create_connection(db: Session, owner: User, address: str) -> GmailConnection:
    connection = GmailConnection(
        agency_id=owner.agency_id,
        user_id=owner.id,
        gmail_address=address,
        status=GmailConnectionStatus.CONNECTED,
        connected_at=utc_now(),
    )
    db.add(connection)
    db.flush()
    db.add(
        GmailOAuthCredential(
            gmail_connection_id=connection.id,
            encrypted_access_token="encrypted-access",
            encrypted_refresh_token="encrypted-refresh",
            access_token_expires_at=utc_now() + timedelta(hours=1),
            granted_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
    )
    db.commit()
    return connection


def test_approved_ingestion_is_received_idempotent_and_paginates(
    seeded_db: Session,
) -> None:
    owner = seeded_db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert owner is not None
    connection = create_connection(seeded_db, owner, "sync@gmail.test")
    mailbox = FakeMailbox(
        [
            gmail_message("approved-1", "alerts@americo.com", attachment=True),
            gmail_message("unapproved-1", "friend@example.test", body="Never persist this body"),
        ]
    )

    def factory(credential):
        return mailbox, False

    first = sync_connection(seeded_db, connection.id, mailbox_factory=factory)
    assert first.messages_seen == 2
    assert first.approved == first.ingested == 1
    assert first.skipped_unapproved == 1
    assert first.attachments_discovered == 1
    assert mailbox.list_calls == [None, "next"]
    assert mailbox.full_fetches == ["approved-1"]

    stored = seeded_db.scalar(
        select(CarrierMessage).where(CarrierMessage.gmail_message_id == "approved-1")
    )
    assert stored is not None
    assert stored.processing_status is ProcessingStatus.RECEIVED
    assert stored.classification is stored.summary is stored.priority is stored.case_id is None
    assert stored.sender == "alerts@americo.com"
    assert stored.gmail_thread_id == "thread-approved-1"
    observed = seeded_db.scalar(
        select(GmailObservedMessage).where(
            GmailObservedMessage.gmail_connection_id == connection.id,
            GmailObservedMessage.gmail_message_id == "approved-1",
        )
    )
    assert observed is not None
    assert observed.gmail_thread_id == "thread-approved-1"
    attachment = seeded_db.scalar(
        select(Attachment).where(Attachment.carrier_message_id == stored.id)
    )
    assert attachment is not None
    assert attachment.processing_status.value == "PENDING"
    assert attachment.extracted_text is None
    assert not seeded_db.scalars(
        select(CarrierMessage).where(CarrierMessage.raw_content.contains("Never persist"))
    ).all()

    second = sync_connection(seeded_db, connection.id, mailbox_factory=factory)
    assert second.ingested == 0
    assert second.already_ingested == 1
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(CarrierMessage)
            .where(
                CarrierMessage.gmail_connection_id == connection.id,
                CarrierMessage.gmail_message_id == "approved-1",
            )
        )
        == 1
    )
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(GmailObservedMessage)
            .where(
                GmailObservedMessage.gmail_connection_id == connection.id,
                GmailObservedMessage.gmail_message_id == "approved-1",
            )
        )
        == 1
    )


def test_observed_message_is_not_replayed_after_operational_message_deletion(
    seeded_db: Session,
) -> None:
    owner = seeded_db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert owner is not None
    connection = create_connection(seeded_db, owner, "replay-safe@gmail.test")
    mailbox = FakeMailbox([gmail_message("old-x", "alerts@americo.com")])

    def factory(credential):
        return mailbox, False

    first = sync_connection(seeded_db, connection.id, mailbox_factory=factory)
    assert first.ingested == 1
    stored = seeded_db.scalar(
        select(CarrierMessage).where(
            CarrierMessage.gmail_connection_id == connection.id,
            CarrierMessage.gmail_message_id == "old-x",
        )
    )
    assert stored is not None
    seeded_db.execute(delete(AuditEvent).where(AuditEvent.carrier_message_id == stored.id))
    seeded_db.execute(delete(CarrierMessage).where(CarrierMessage.id == stored.id))
    seeded_db.commit()

    assert seeded_db.get(CarrierMessage, stored.id) is None
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(GmailObservedMessage)
            .where(
                GmailObservedMessage.gmail_connection_id == connection.id,
                GmailObservedMessage.gmail_message_id == "old-x",
            )
        )
        == 1
    )

    replay = sync_connection(seeded_db, connection.id, mailbox_factory=factory)
    assert replay.ingested == 0
    assert replay.already_ingested == 1
    assert (
        seeded_db.scalar(
            select(CarrierMessage.id).where(
                CarrierMessage.gmail_connection_id == connection.id,
                CarrierMessage.gmail_message_id == "old-x",
            )
        )
        is None
    )

    mailbox.messages["new-y"] = gmail_message("new-y", "alerts@americo.com")
    with_new_message = sync_connection(seeded_db, connection.id, mailbox_factory=factory)
    assert with_new_message.ingested == 1
    assert with_new_message.already_ingested == 1
    assert (
        seeded_db.scalar(
            select(CarrierMessage.id).where(
                CarrierMessage.gmail_connection_id == connection.id,
                CarrierMessage.gmail_message_id == "new-y",
            )
        )
        is not None
    )


def test_same_gmail_id_is_safe_across_connections(seeded_db: Session) -> None:
    owners = seeded_db.scalars(select(User).where(User.role == "AGENT").order_by(User.id)).all()
    assert len(owners) == 2
    first_connection = create_connection(seeded_db, owners[0], "first@gmail.test")
    second_connection = create_connection(seeded_db, owners[1], "second@gmail.test")
    fixture = gmail_message("shared-id", "alerts@americo.com")
    first_mailbox = FakeMailbox([fixture])
    second_mailbox = FakeMailbox([fixture])
    assert (
        sync_connection(
            seeded_db,
            first_connection.id,
            mailbox_factory=lambda credential: (first_mailbox, False),
        ).ingested
        == 1
    )
    assert (
        sync_connection(
            seeded_db,
            second_connection.id,
            mailbox_factory=lambda credential: (second_mailbox, False),
        ).ingested
        == 1
    )
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(CarrierMessage)
            .where(CarrierMessage.gmail_message_id == "shared-id")
        )
        == 2
    )
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(GmailObservedMessage)
            .where(GmailObservedMessage.gmail_message_id == "shared-id")
        )
        == 2
    )


def test_ledger_follows_logical_mailbox_across_reconnect_and_handoff(
    seeded_db: Session,
) -> None:
    owners = seeded_db.scalars(select(User).where(User.role == "AGENT").order_by(User.id)).all()
    assert len(owners) == 2
    connection = create_connection(seeded_db, owners[0], "stable-mailbox@gmail.test")
    mailbox = FakeMailbox([gmail_message("stable-x", "alerts@americo.com")])

    def factory(credential):
        return mailbox, False

    assert sync_connection(seeded_db, connection.id, mailbox_factory=factory).ingested == 1

    stored = seeded_db.scalar(
        select(CarrierMessage).where(
            CarrierMessage.gmail_connection_id == connection.id,
            CarrierMessage.gmail_message_id == "stable-x",
        )
    )
    assert stored is not None
    seeded_db.execute(delete(AuditEvent).where(AuditEvent.carrier_message_id == stored.id))
    seeded_db.execute(delete(CarrierMessage).where(CarrierMessage.id == stored.id))
    connection.status = GmailConnectionStatus.DISCONNECTED
    seeded_db.commit()

    connection.status = GmailConnectionStatus.CONNECTED
    seeded_db.commit()
    reconnect = sync_connection(seeded_db, connection.id, mailbox_factory=factory)
    assert reconnect.already_ingested == 1
    assert reconnect.ingested == 0

    connection.user_id = owners[1].id
    seeded_db.commit()
    handoff = sync_connection(seeded_db, connection.id, mailbox_factory=factory)
    assert handoff.already_ingested == 1
    assert handoff.ingested == 0
    assert (
        seeded_db.scalar(
            select(CarrierMessage.id).where(
                CarrierMessage.gmail_connection_id == connection.id,
                CarrierMessage.gmail_message_id == "stable-x",
            )
        )
        is None
    )


def test_same_mailbox_observed_identity_has_database_concurrency_guard(
    seeded_db: Session,
) -> None:
    owner = seeded_db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert owner is not None
    connection = create_connection(seeded_db, owner, "concurrency@gmail.test")
    first_seen = utc_now()
    seeded_db.add(
        GmailObservedMessage(
            gmail_connection_id=connection.id,
            gmail_message_id="concurrent-x",
            gmail_thread_id="thread-concurrent-x",
            first_seen_at=first_seen,
        )
    )
    seeded_db.commit()

    with pytest.raises(IntegrityError), seeded_db.begin_nested():
        seeded_db.add(
            GmailObservedMessage(
                gmail_connection_id=connection.id,
                gmail_message_id="concurrent-x",
                gmail_thread_id="thread-concurrent-x",
                first_seen_at=first_seen,
            )
        )
        seeded_db.flush()

    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(GmailObservedMessage)
            .where(
                GmailObservedMessage.gmail_connection_id == connection.id,
                GmailObservedMessage.gmail_message_id == "concurrent-x",
            )
        )
        == 1
    )


def test_observed_message_backfill_is_complete_idempotent_and_independent(
    seeded_db: Session,
) -> None:
    owners = seeded_db.scalars(select(User).where(User.role == "AGENT").order_by(User.id)).all()
    assert len(owners) == 2
    first_connection = create_connection(seeded_db, owners[0], "legacy-one@gmail.test")
    second_connection = create_connection(seeded_db, owners[1], "legacy-two@gmail.test")
    carrier = seeded_db.scalar(select(Carrier.id).where(Carrier.name == "Americo"))
    assert carrier is not None
    legacy_messages = [
        CarrierMessage(
            agency_id=owners[index].agency_id,
            carrier_id=carrier,
            gmail_connection_id=connection.id,
            gmail_message_id="legacy-shared-id",
            gmail_thread_id=f"legacy-thread-{index}",
            sender="alerts@americo.com",
            subject=f"Legacy message {index}",
            received_at=utc_now(),
            processing_status=ProcessingStatus.RECEIVED,
            raw_content="Synthetic legacy content.",
            cleaned_content="Synthetic legacy content.",
        )
        for index, connection in enumerate([first_connection, second_connection])
    ]
    seeded_db.add_all(legacy_messages)
    seeded_db.commit()

    assert backfill_observed_messages(seeded_db) == 2
    seeded_db.commit()
    assert backfill_observed_messages(seeded_db) == 0
    seeded_db.commit()
    assert seeded_db.scalar(select(func.count()).select_from(GmailObservedMessage)) == 2

    seeded_db.execute(delete(CarrierMessage).where(CarrierMessage.id == legacy_messages[0].id))
    seeded_db.commit()
    assert (
        seeded_db.scalar(
            select(GmailObservedMessage.id).where(
                GmailObservedMessage.gmail_connection_id == first_connection.id,
                GmailObservedMessage.gmail_message_id == "legacy-shared-id",
            )
        )
        is not None
    )
    assert (
        seeded_db.scalar(
            select(func.count())
            .select_from(GmailObservedMessage)
            .where(GmailObservedMessage.gmail_message_id == "legacy-shared-id")
        )
        == 2
    )


def test_unrelated_integrity_error_is_not_misreported_as_duplicate(seeded_db: Session) -> None:
    owner = seeded_db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert owner is not None
    connection = create_connection(seeded_db, owner, "integrity@gmail.test")
    fixture = gmail_message("bad-attachments", "alerts@americo.com", attachment=True)
    duplicate = dict(fixture["payload"]["parts"][1])
    duplicate["partId"] = "2"
    fixture["payload"]["parts"].append(duplicate)
    mailbox = FakeMailbox([fixture])

    with pytest.raises(GmailTransientError, match="failed safely"):
        sync_connection(
            seeded_db,
            connection.id,
            mailbox_factory=lambda credential: (mailbox, False),
        )

    seeded_db.refresh(connection)
    assert connection.status is GmailConnectionStatus.ERROR
    assert (
        seeded_db.scalar(
            select(CarrierMessage).where(CarrierMessage.gmail_message_id == "bad-attachments")
        )
        is None
    )
    assert (
        seeded_db.scalar(
            select(GmailObservedMessage.id).where(
                GmailObservedMessage.gmail_connection_id == connection.id,
                GmailObservedMessage.gmail_message_id == "bad-attachments",
            )
        )
        is None
    )


def test_realistic_long_gmail_attachment_identity_is_persisted(seeded_db: Session) -> None:
    owner = seeded_db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert owner is not None
    connection = create_connection(seeded_db, owner, "long-attachment@gmail.test")
    fixture = gmail_message("long-attachment", "alerts@americo.com", attachment=True)
    long_identity = "opaque-" + "x" * 397
    fixture["payload"]["parts"][1]["body"]["attachmentId"] = long_identity
    mailbox = FakeMailbox([fixture])

    result = sync_connection(
        seeded_db,
        connection.id,
        mailbox_factory=lambda credential: (mailbox, False),
    )

    assert result.ingested == 1
    attachment = seeded_db.scalar(
        select(Attachment)
        .join(CarrierMessage)
        .where(CarrierMessage.gmail_message_id == "long-attachment")
    )
    assert attachment is not None
    assert attachment.external_id == long_identity


def test_sync_credential_and_transient_errors_update_health(seeded_db: Session) -> None:
    owner = seeded_db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert owner is not None
    connection = create_connection(seeded_db, owner, "errors@gmail.test")

    def reauth_factory(credential):
        raise GmailReauthorizationRequired("synthetic invalid grant")

    with pytest.raises(GmailReauthorizationRequired):
        sync_connection(seeded_db, connection.id, mailbox_factory=reauth_factory)
    seeded_db.refresh(connection)
    assert connection.status is GmailConnectionStatus.NEEDS_REAUTH
    assert "invalid grant" not in (connection.last_error_summary or "")

    connection.status = GmailConnectionStatus.CONNECTED
    seeded_db.commit()

    def transient_factory(credential):
        raise GmailTransientError("synthetic provider body with unsafe detail")

    with pytest.raises(GmailTransientError):
        sync_connection(seeded_db, connection.id, mailbox_factory=transient_factory)
    seeded_db.refresh(connection)
    assert connection.status is GmailConnectionStatus.ERROR
    assert "unsafe detail" not in (connection.last_error_summary or "")

    recovered = FakeMailbox([])
    sync_connection(
        seeded_db,
        connection.id,
        mailbox_factory=lambda credential: (recovered, False),
    )
    seeded_db.refresh(connection)
    assert connection.status is GmailConnectionStatus.CONNECTED
    assert connection.last_error_summary is None
    event_types = set(
        seeded_db.scalars(
            select(AuditEvent.event_type).where(AuditEvent.agency_id == owner.agency_id)
        ).all()
    )
    assert {"GMAIL_REAUTH_REQUIRED", "GMAIL_SYNC_FAILED", "GMAIL_SYNC_COMPLETED"} <= event_types


def test_missing_credentials_and_unexpected_failures_update_health(seeded_db: Session) -> None:
    owner = seeded_db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert owner is not None
    missing = GmailConnection(
        agency_id=owner.agency_id,
        user_id=owner.id,
        gmail_address="missing-credential@gmail.test",
        status=GmailConnectionStatus.CONNECTED,
    )
    seeded_db.add(missing)
    seeded_db.commit()

    with pytest.raises(GmailReauthorizationRequired):
        sync_connection(seeded_db, missing.id)
    seeded_db.refresh(missing)
    assert missing.status is GmailConnectionStatus.NEEDS_REAUTH
    assert missing.last_attempted_sync_at is not None

    unexpected = create_connection(seeded_db, owner, "unexpected-error@gmail.test")

    def broken_factory(credential):
        raise RuntimeError("synthetic unsafe implementation detail")

    with pytest.raises(GmailTransientError, match="failed safely"):
        sync_connection(seeded_db, unexpected.id, mailbox_factory=broken_factory)
    seeded_db.refresh(unexpected)
    assert unexpected.status is GmailConnectionStatus.ERROR
    assert "unsafe" not in (unexpected.last_error_summary or "")


def test_worker_isolates_a_broken_connection(test_engine) -> None:
    connection = test_engine.connect()
    transaction = connection.begin()
    TestingSession = sessionmaker(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        with TestingSession() as db:
            seed_demo_data(db, "worker-test-password")
            owners = db.scalars(select(User).where(User.role == "AGENT").order_by(User.id)).all()
            broken = create_connection(db, owners[0], "broken-worker@gmail.test")
            healthy = create_connection(db, owners[1], "healthy-worker@gmail.test")

        called: list[int] = []

        def fake_sync(db: Session, connection_id: int) -> SyncResult:
            called.append(connection_id)
            if connection_id == broken.id:
                raise GmailTransientError("synthetic failure")
            return SyncResult(connection_id=connection_id)

        results = poll_once(
            sync_function=fake_sync,
            session_factory=TestingSession,
        )
        assert called == [broken.id, healthy.id]
        assert [item.connection_id for item in results] == [healthy.id]
    finally:
        transaction.rollback()
        connection.close()


def test_worker_skips_connections_owned_by_disabled_or_removed_agents(test_engine) -> None:
    connection = test_engine.connect()
    transaction = connection.begin()
    TestingSession = sessionmaker(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        with TestingSession() as db:
            seed_demo_data(db, "worker-test-password")
            owners = db.scalars(select(User).where(User.role == "AGENT").order_by(User.id)).all()
            disabled = create_connection(db, owners[0], "disabled-worker@gmail.test")
            removed = create_connection(db, owners[1], "removed-worker@gmail.test")
            owners[0].is_active = False
            owners[1].removed_at = utc_now()
            db.commit()

        called: list[int] = []

        def fake_sync(_db: Session, connection_id: int) -> SyncResult:
            called.append(connection_id)
            return SyncResult(connection_id=connection_id)

        assert poll_once(sync_function=fake_sync, session_factory=TestingSession) == []
        assert called == []
        assert disabled.id != removed.id
    finally:
        transaction.rollback()
        connection.close()


def test_worker_configures_windows_break_for_graceful_shutdown(monkeypatch) -> None:
    configured: list[tuple[object, object]] = []
    fake_sigbreak = object()

    monkeypatch.setattr("app.workers.gmail_poll.signal.SIGBREAK", fake_sigbreak, raising=False)
    monkeypatch.setattr(
        "app.workers.gmail_poll.signal.signal",
        lambda signum, handler: configured.append((signum, handler)),
    )

    _configure_shutdown_signals()

    assert len(configured) == 1
    signum, handler = configured[0]
    assert signum is fake_sigbreak
    with pytest.raises(KeyboardInterrupt):
        handler(0, None)
