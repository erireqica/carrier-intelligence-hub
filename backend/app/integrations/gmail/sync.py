from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.time import utc_now
from app.integrations.gmail.client import GmailMailbox, mailbox_from_credential
from app.integrations.gmail.errors import (
    GmailReauthorizationRequired,
    GmailTransientError,
)
from app.integrations.gmail.matcher import match_carrier
from app.integrations.gmail.parser import normalized_sender, parse_message
from app.models.enums import (
    AttachmentStatus,
    AuditSeverity,
    GmailConnectionStatus,
    ProcessingStatus,
)
from app.models.operations import Attachment, CarrierMessage
from app.models.organization import GmailConnection, GmailOAuthCredential
from app.services.audit import record_audit_event

MailboxFactory = Callable[[GmailOAuthCredential], tuple[GmailMailbox, bool]]


@dataclass
class SyncResult:
    connection_id: int
    messages_seen: int = 0
    already_ingested: int = 0
    approved: int = 0
    ingested: int = 0
    skipped_unapproved: int = 0
    attachments_discovered: int = 0


def _received_at(message: dict) -> datetime:
    try:
        return datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=UTC)
    except KeyError, TypeError, ValueError, OSError:
        return utc_now()


def _connection_with_credential(db: Session, connection_id: int) -> GmailConnection | None:
    return db.scalar(
        select(GmailConnection)
        .options(joinedload(GmailConnection.oauth_credential))
        .where(GmailConnection.id == connection_id)
    )


def _record_failure(
    db: Session,
    connection_id: int,
    *,
    status: GmailConnectionStatus,
    summary: str,
    event_type: str,
) -> None:
    db.rollback()
    connection = db.get(GmailConnection, connection_id)
    if connection is None:
        return
    connection.status = status
    connection.last_error_summary = summary
    record_audit_event(
        db,
        agency_id=connection.agency_id,
        event_type=event_type,
        severity=AuditSeverity.WARNING
        if status is GmailConnectionStatus.NEEDS_REAUTH
        else AuditSeverity.ERROR,
        description=(
            "Gmail authorization requires reconnection"
            if status is GmailConnectionStatus.NEEDS_REAUTH
            else "Gmail synchronization failed"
        ),
        metadata={"connection_id": connection.id},
    )
    db.commit()


def sync_connection(
    db: Session,
    connection_id: int,
    *,
    mailbox_factory: MailboxFactory = mailbox_from_credential,
) -> SyncResult:
    connection = _connection_with_credential(db, connection_id)
    if connection is None:
        raise LookupError("Gmail connection not found")

    result = SyncResult(connection_id=connection.id)
    connection.last_attempted_sync_at = utc_now()
    db.commit()

    try:
        if connection.oauth_credential is None:
            raise GmailReauthorizationRequired(
                "Google authorization is no longer valid. Reconnect this inbox."
            )
        mailbox, refreshed = mailbox_factory(connection.oauth_credential)
        if refreshed:
            db.commit()
        query = f"in:inbox is:unread newer_than:{get_settings().gmail_initial_lookback_days}d"
        page_token: str | None = None
        while True:
            page = mailbox.list_messages(query, page_token)
            for listed in page.get("messages", []) or []:
                message_id = str(listed.get("id") or "")
                if not message_id:
                    continue
                result.messages_seen += 1
                exists = db.scalar(
                    select(CarrierMessage.id).where(
                        CarrierMessage.gmail_connection_id == connection.id,
                        CarrierMessage.gmail_message_id == message_id,
                    )
                )
                db.commit()
                if exists is not None:
                    result.already_ingested += 1
                    continue

                metadata = dict(mailbox.get_metadata(message_id))
                sender = normalized_sender(metadata)
                carrier = match_carrier(db, connection.agency_id, sender)
                db.commit()
                if carrier is None:
                    result.skipped_unapproved += 1
                    continue
                result.approved += 1

                full_message = dict(mailbox.get_full_message(message_id))
                parsed = parse_message(full_message)
                message = CarrierMessage(
                    agency_id=connection.agency_id,
                    case_id=None,
                    carrier_id=carrier.id,
                    gmail_connection_id=connection.id,
                    gmail_message_id=message_id,
                    gmail_thread_id=str(full_message.get("threadId") or "") or None,
                    sender=sender,
                    subject=parsed.subject,
                    received_at=_received_at(full_message),
                    classification=None,
                    summary=None,
                    priority=None,
                    processing_status=ProcessingStatus.RECEIVED,
                    raw_content=parsed.raw_content,
                    cleaned_content=parsed.cleaned_content,
                )
                db.add(message)
                try:
                    db.flush()
                    for item in parsed.attachments:
                        db.add(
                            Attachment(
                                carrier_message_id=message.id,
                                external_id=item.external_id,
                                filename=item.filename,
                                mime_type=item.mime_type,
                                size_bytes=item.size_bytes,
                                processing_status=AttachmentStatus.PENDING,
                                extracted_text=None,
                            )
                        )
                    record_audit_event(
                        db,
                        agency_id=connection.agency_id,
                        carrier_message_id=message.id,
                        event_type="GMAIL_MESSAGE_INGESTED",
                        description="Approved Gmail message ingested for later processing",
                        metadata={
                            "connection_id": connection.id,
                            "carrier_id": carrier.id,
                            "attachment_count": len(parsed.attachments),
                        },
                    )
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    result.already_ingested += 1
                    continue
                result.ingested += 1
                result.attachments_discovered += len(parsed.attachments)

            next_page_token = page.get("nextPageToken")
            if not next_page_token:
                break
            page_token = str(next_page_token)

        connection = db.get(GmailConnection, connection_id)
        assert connection is not None
        connection.status = GmailConnectionStatus.CONNECTED
        connection.last_successful_sync_at = utc_now()
        connection.last_error_summary = None
        record_audit_event(
            db,
            agency_id=connection.agency_id,
            event_type="GMAIL_SYNC_COMPLETED",
            description="Gmail synchronization completed",
            metadata=asdict(result),
        )
        db.commit()
        return result
    except GmailReauthorizationRequired:
        _record_failure(
            db,
            connection_id,
            status=GmailConnectionStatus.NEEDS_REAUTH,
            summary="Google authorization is no longer valid. Reconnect this inbox.",
            event_type="GMAIL_REAUTH_REQUIRED",
        )
        raise
    except GmailTransientError:
        _record_failure(
            db,
            connection_id,
            status=GmailConnectionStatus.ERROR,
            summary="Gmail could not be reached. Try syncing again.",
            event_type="GMAIL_SYNC_FAILED",
        )
        raise
    except Exception as error:
        _record_failure(
            db,
            connection_id,
            status=GmailConnectionStatus.ERROR,
            summary="Gmail could not be reached. Try syncing again.",
            event_type="GMAIL_SYNC_FAILED",
        )
        raise GmailTransientError("Gmail synchronization failed safely.") from error
