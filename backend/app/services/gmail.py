import secrets
from dataclasses import asdict
from datetime import UTC, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.schemas.domain import (
    AgentBrief,
    CarrierBrief,
    GmailConnectionItem,
    GmailConnectionsResponse,
    GmailMessageListItem,
    GmailOAuthStartResponse,
    GmailSyncResult,
)
from app.core.config import get_settings
from app.core.security import normalize_email, token_hash
from app.core.time import utc_now
from app.integrations.gmail.crypto import TokenCipher
from app.integrations.gmail.oauth import GMAIL_MODIFY_SCOPE, GoogleOAuthClient, OAuthTokenSet
from app.integrations.gmail.sync import MailboxFactory, sync_connection
from app.models.enums import (
    GmailConnectionStatus,
    GmailLabelSyncStatus,
    ReviewStatus,
    UserRole,
)
from app.models.gmail_labels import GmailThreadLabelSync
from app.models.operations import Attachment, CarrierMessage, ReviewItem
from app.models.organization import (
    GmailConnection,
    GmailOAuthCredential,
    GmailOAuthState,
)
from app.services.audit import record_audit_event
from app.services.auth import AuthContext

OAUTH_STATE_LIFETIME = timedelta(minutes=10)


def _owner_brief(connection: GmailConnection) -> AgentBrief:
    return AgentBrief(
        id=connection.owner.id,
        full_name=connection.owner.full_name,
        email=connection.owner.email,
    )


def connection_item(
    db: Session, connection: GmailConnection, current: AuthContext
) -> GmailConnectionItem:
    credential = connection.oauth_credential
    can_apply_labels = bool(credential and GMAIL_MODIFY_SCOPE in credential.granted_scopes)
    pending = (
        db.scalar(
            select(func.count())
            .select_from(GmailThreadLabelSync)
            .where(
                GmailThreadLabelSync.gmail_connection_id == connection.id,
                GmailThreadLabelSync.status.in_(
                    [
                        GmailLabelSyncStatus.PENDING,
                        GmailLabelSyncStatus.PROCESSING,
                        GmailLabelSyncStatus.RETRY_WAIT,
                    ]
                ),
            )
        )
        or 0
    )
    failed = (
        db.scalar(
            select(func.count())
            .select_from(GmailThreadLabelSync)
            .where(
                GmailThreadLabelSync.gmail_connection_id == connection.id,
                GmailThreadLabelSync.status.in_(
                    [GmailLabelSyncStatus.FAILED, GmailLabelSyncStatus.NEEDS_PERMISSION]
                ),
            )
        )
        or 0
    )
    return GmailConnectionItem(
        id=connection.id,
        gmail_address=connection.gmail_address,
        owner=_owner_brief(connection),
        status=connection.status,
        connected_at=connection.connected_at,
        last_successful_sync_at=connection.last_successful_sync_at,
        last_attempted_sync_at=connection.last_attempted_sync_at,
        last_error_summary=connection.last_error_summary,
        is_owner=connection.user_id == current.user.id,
        can_apply_workflow_labels=can_apply_labels,
        pending_label_sync_count=pending,
        failed_label_sync_count=failed,
    )


def list_connections(db: Session, current: AuthContext) -> GmailConnectionsResponse:
    query = (
        select(GmailConnection)
        .options(
            joinedload(GmailConnection.owner),
            joinedload(GmailConnection.oauth_credential),
        )
        .where(GmailConnection.agency_id == current.user.agency_id)
        .where(GmailConnection.status != GmailConnectionStatus.DISCONNECTED)
    )
    if current.user.role is UserRole.AGENT:
        query = query.where(GmailConnection.user_id == current.user.id)
    connections = db.scalars(query.order_by(GmailConnection.created_at.desc())).all()
    return GmailConnectionsResponse(
        configured=get_settings().gmail_oauth_configured,
        connections=[connection_item(db, item, current) for item in connections],
    )


def get_connection(
    db: Session,
    current: AuthContext,
    connection_id: int,
    *,
    manager_can_access: bool,
) -> GmailConnection:
    connection = db.scalar(
        select(GmailConnection)
        .options(
            joinedload(GmailConnection.owner),
            joinedload(GmailConnection.oauth_credential),
        )
        .where(
            GmailConnection.id == connection_id,
            GmailConnection.agency_id == current.user.agency_id,
        )
    )
    permitted = connection is not None and (
        connection.user_id == current.user.id
        or (manager_can_access and current.user.role is UserRole.MANAGER)
    )
    if not permitted:
        raise HTTPException(status_code=404, detail="Gmail connection not found")
    assert connection is not None
    return connection


def start_oauth(
    db: Session,
    current: AuthContext,
    reconnect_connection_id: int | None,
    *,
    oauth_client: GoogleOAuthClient | None = None,
) -> GmailOAuthStartResponse:
    settings = get_settings()
    if not settings.gmail_oauth_configured:
        raise HTTPException(status_code=503, detail="Gmail integration is not configured")
    if reconnect_connection_id is not None:
        get_connection(
            db,
            current,
            reconnect_connection_id,
            manager_can_access=False,
        )
    raw_state = secrets.token_urlsafe(48)
    now = utc_now()
    db.add(
        GmailOAuthState(
            state_hash=token_hash(raw_state),
            agency_id=current.user.agency_id,
            user_id=current.user.id,
            auth_session_id=current.session.id,
            reconnect_connection_id=reconnect_connection_id,
            created_at=now,
            expires_at=now + OAUTH_STATE_LIFETIME,
        )
    )
    db.commit()
    client = oauth_client or GoogleOAuthClient(settings)
    return GmailOAuthStartResponse(authorization_url=client.authorization_url(raw_state))


def consume_oauth_state(
    db: Session, current: AuthContext | None, raw_state: str | None
) -> GmailOAuthState | None:
    if current is None or not raw_state:
        return None
    state = db.scalar(
        select(GmailOAuthState)
        .where(GmailOAuthState.state_hash == token_hash(raw_state))
        .with_for_update()
    )
    now = utc_now()
    if (
        state is None
        or state.consumed_at is not None
        or state.expires_at <= now
        or state.agency_id != current.user.agency_id
        or state.user_id != current.user.id
        or state.auth_session_id != current.session.id
    ):
        db.rollback()
        return None
    state.consumed_at = now
    db.commit()
    return state


def complete_oauth(
    db: Session,
    current: AuthContext,
    state: GmailOAuthState,
    tokens: OAuthTokenSet,
    *,
    cipher: TokenCipher | None = None,
) -> GmailConnection:
    if GMAIL_MODIFY_SCOPE not in tokens.granted_scopes:
        raise PermissionError("Required Gmail workflow-label scope was not granted")
    gmail_address = normalize_email(tokens.gmail_address)
    existing = db.scalar(
        select(GmailConnection)
        .options(joinedload(GmailConnection.oauth_credential))
        .where(
            GmailConnection.agency_id == current.user.agency_id,
            GmailConnection.gmail_address == gmail_address,
            GmailConnection.status != GmailConnectionStatus.DISCONNECTED,
        )
    )
    target = (
        db.scalar(
            select(GmailConnection)
            .options(joinedload(GmailConnection.oauth_credential))
            .where(
                GmailConnection.id == state.reconnect_connection_id,
                GmailConnection.agency_id == current.user.agency_id,
                GmailConnection.user_id == current.user.id,
                GmailConnection.status != GmailConnectionStatus.DISCONNECTED,
            )
        )
        if state.reconnect_connection_id is not None
        else None
    )
    if state.reconnect_connection_id is not None and target is None:
        raise LookupError("Reconnect target is unavailable")
    if target is not None and target.gmail_address != gmail_address:
        raise ValueError("Authorized Gmail account does not match the reconnect target")
    if existing is not None and existing.user_id != current.user.id:
        raise FileExistsError("This Gmail inbox is already connected to another agency user")
    if target is not None and existing is not None and target.id != existing.id:
        raise FileExistsError("This Gmail inbox is already connected")

    connection = target or existing
    reconnecting = connection is not None
    if connection is None:
        connection = GmailConnection(
            agency_id=current.user.agency_id,
            user_id=current.user.id,
            gmail_address=gmail_address,
            google_account_id=gmail_address,
            status=GmailConnectionStatus.CONNECTED,
        )
        db.add(connection)
        db.flush()

    token_cipher = cipher or TokenCipher.from_settings()
    credential = connection.oauth_credential
    if credential is None and not tokens.refresh_token:
        raise ValueError("Google did not provide offline authorization")
    if credential is None:
        assert tokens.refresh_token is not None
        credential = GmailOAuthCredential(
            gmail_connection_id=connection.id,
            encrypted_refresh_token=token_cipher.encrypt(tokens.refresh_token),
            granted_scopes=tokens.granted_scopes,
        )
        db.add(credential)
    elif tokens.refresh_token:
        credential.encrypted_refresh_token = token_cipher.encrypt(tokens.refresh_token)
    if tokens.access_token:
        credential.encrypted_access_token = token_cipher.encrypt(tokens.access_token)
    expires_at = tokens.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    credential.access_token_expires_at = expires_at
    credential.granted_scopes = tokens.granted_scopes

    connection.status = GmailConnectionStatus.CONNECTED
    connection.connected_at = utc_now()
    connection.last_error_summary = None
    event_type = "GMAIL_RECONNECTED" if reconnecting else "GMAIL_CONNECTED"
    record_audit_event(
        db,
        agency_id=connection.agency_id,
        actor_user_id=current.user.id,
        event_type=event_type,
        description=("Gmail inbox reconnected" if reconnecting else "Gmail inbox connected"),
        metadata={"connection_id": connection.id},
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise FileExistsError("This Gmail inbox is already connected") from error
    from app.services.gmail_labels import reset_connection_label_syncs

    reset_connection_label_syncs(db, connection.id)
    return connection


def run_manual_sync(
    db: Session,
    current: AuthContext,
    connection_id: int,
    *,
    mailbox_factory: MailboxFactory | None = None,
) -> GmailSyncResult:
    connection = get_connection(db, current, connection_id, manager_can_access=True)
    if connection.status in {
        GmailConnectionStatus.DISCONNECTED,
        GmailConnectionStatus.NEEDS_REAUTH,
    }:
        raise HTTPException(status_code=409, detail="Reconnect this Gmail inbox before syncing")
    result = (
        sync_connection(db, connection.id, mailbox_factory=mailbox_factory)
        if mailbox_factory
        else sync_connection(db, connection.id)
    )
    return GmailSyncResult(**asdict(result))


def recent_messages(
    db: Session, current: AuthContext, connection_id: int
) -> list[GmailMessageListItem]:
    connection = get_connection(db, current, connection_id, manager_can_access=True)
    open_review_id = (
        select(func.max(ReviewItem.id))
        .where(
            ReviewItem.carrier_message_id == CarrierMessage.id,
            ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
        )
        .correlate(CarrierMessage)
        .scalar_subquery()
    )
    label_sync_status = (
        select(GmailThreadLabelSync.status)
        .where(
            GmailThreadLabelSync.gmail_connection_id == CarrierMessage.gmail_connection_id,
            GmailThreadLabelSync.gmail_thread_id == CarrierMessage.gmail_thread_id,
        )
        .correlate(CarrierMessage)
        .scalar_subquery()
    )
    rows = db.execute(
        select(CarrierMessage, func.count(Attachment.id), open_review_id, label_sync_status)
        .outerjoin(Attachment, Attachment.carrier_message_id == CarrierMessage.id)
        .where(CarrierMessage.gmail_connection_id == connection.id)
        .group_by(CarrierMessage.id)
        .order_by(CarrierMessage.received_at.desc())
        .limit(50)
    ).all()
    return [
        GmailMessageListItem(
            id=message.id,
            carrier=CarrierBrief(
                id=message.carrier.id,
                name=message.carrier.name,
                code=message.carrier.code,
            ),
            sender=message.sender,
            subject=message.subject,
            received_at=message.received_at,
            processing_status=message.processing_status,
            attachment_count=attachment_count,
            case_id=message.case_id,
            review_id=review_id,
            last_processing_error_code=message.last_processing_error_code,
            processing_attempt_count=message.processing_attempt_count,
            processing_next_retry_at=message.processing_next_retry_at,
            label_sync_status=sync_status,
        )
        for message, attachment_count, review_id, sync_status in rows
    ]


def retry_connection_labels(db: Session, current: AuthContext, connection_id: int) -> int:
    connection = get_connection(db, current, connection_id, manager_can_access=True)
    from app.services.gmail_labels import enqueue_thread_label_sync

    thread_ids = db.scalars(
        select(CarrierMessage.gmail_thread_id)
        .where(
            CarrierMessage.gmail_connection_id == connection.id,
            CarrierMessage.gmail_thread_id.is_not(None),
            CarrierMessage.gmail_thread_id != "",
        )
        .distinct()
    ).all()
    for thread_id in thread_ids:
        enqueue_thread_label_sync(
            db,
            agency_id=connection.agency_id,
            gmail_connection_id=connection.id,
            gmail_thread_id=thread_id,
        )
    db.commit()
    return len(thread_ids)


def disconnect(
    db: Session,
    current: AuthContext,
    connection_id: int,
    *,
    oauth_client: GoogleOAuthClient | None = None,
    cipher: TokenCipher | None = None,
) -> None:
    connection = get_connection(db, current, connection_id, manager_can_access=False)
    token_to_revoke: str | None = None
    if connection.oauth_credential is not None:
        try:
            token_cipher = cipher or TokenCipher.from_settings()
            token_to_revoke = token_cipher.decrypt(
                connection.oauth_credential.encrypted_refresh_token
            )
        except Exception:
            token_to_revoke = None
        db.delete(connection.oauth_credential)
    connection.status = GmailConnectionStatus.DISCONNECTED
    connection.last_error_summary = None
    record_audit_event(
        db,
        agency_id=connection.agency_id,
        actor_user_id=current.user.id,
        event_type="GMAIL_DISCONNECTED",
        description="Gmail inbox disconnected",
        metadata={"connection_id": connection.id},
    )
    db.commit()
    if token_to_revoke and get_settings().gmail_oauth_configured:
        (oauth_client or GoogleOAuthClient()).revoke_token(token_to_revoke)
