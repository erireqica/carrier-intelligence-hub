import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.api.dependencies import CsrfUser, CurrentUser, DbSession
from app.api.schemas.auth import MessageResponse
from app.api.schemas.domain import (
    GmailConnectionsResponse,
    GmailMessageListItem,
    GmailOAuthStartRequest,
    GmailOAuthStartResponse,
    GmailSyncResult,
)
from app.core.config import get_settings
from app.integrations.gmail.errors import (
    GmailIntegrationNotConfigured,
    GmailProfileError,
    GmailProfileRequestError,
    GmailProfileValidationError,
    GmailReauthorizationRequired,
    GmailTokenExchangeError,
    GmailTransientError,
)
from app.integrations.gmail.oauth import (
    GMAIL_MODIFY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GoogleOAuthClient,
)
from app.services import gmail as gmail_service
from app.services.auth import resolve_session

router = APIRouter(tags=["gmail"])
logger = logging.getLogger("carrier_hub.gmail_oauth")


def _frontend_redirect(result: str) -> RedirectResponse:
    origin = str(get_settings().frontend_origin).rstrip("/")
    return RedirectResponse(
        f"{origin}/gmail-connections?{urlencode({'oauth': result})}",
        status_code=303,
    )


@router.get("/gmail-connections", response_model=GmailConnectionsResponse)
def get_gmail_connections(current: CurrentUser, db: DbSession) -> GmailConnectionsResponse:
    return gmail_service.list_connections(db, current)


@router.post("/gmail/oauth/start", response_model=GmailOAuthStartResponse)
def start_gmail_oauth(
    data: GmailOAuthStartRequest,
    current: CsrfUser,
    db: DbSession,
) -> GmailOAuthStartResponse:
    try:
        client = GoogleOAuthClient()
    except GmailIntegrationNotConfigured as error:
        raise HTTPException(
            status_code=503, detail="Gmail integration is not configured"
        ) from error
    return gmail_service.start_oauth(
        db,
        current,
        data.reconnect_connection_id,
        oauth_client=client,
    )


@router.get("/gmail/oauth/callback", include_in_schema=False)
def gmail_oauth_callback(request: Request, db: DbSession) -> RedirectResponse:
    settings = get_settings()
    raw_session = request.cookies.get(settings.session_cookie_name)
    current = resolve_session(db, raw_session) if raw_session else None
    state = gmail_service.consume_oauth_state(db, current, request.query_params.get("state"))
    if state is None or current is None:
        return _frontend_redirect("invalid_state")
    if request.query_params.get("error"):
        return _frontend_redirect(
            "denied" if request.query_params.get("error") == "access_denied" else "failed"
        )
    code = request.query_params.get("code")
    if not code:
        return _frontend_redirect("failed")
    try:
        tokens = GoogleOAuthClient().exchange_code(code)
        logger.info(
            "Gmail OAuth token exchange succeeded modify_granted=%s "
            "readonly_also_granted=%s refresh_token_returned=%s",
            GMAIL_MODIFY_SCOPE in tokens.granted_scopes,
            GMAIL_READONLY_SCOPE in tokens.granted_scopes,
            tokens.refresh_token is not None,
        )
        gmail_service.complete_oauth(db, current, state, tokens)
    except PermissionError:
        logger.warning("Gmail OAuth callback failed stage=scope_validation")
        return _frontend_redirect("scope_missing")
    except GmailTokenExchangeError as error:
        logger.warning("Gmail OAuth callback failed stage=token_exchange reason=%s", error.reason)
        return _frontend_redirect("failed")
    except GmailProfileRequestError as error:
        logger.warning(
            "Gmail OAuth callback failed stage=gmail_profile outcome=http_api_failure "
            "status=%s reason=%s during_execute=%s",
            error.status_code if error.status_code is not None else "none",
            error.reason,
            error.during_execute,
        )
        return _frontend_redirect("failed")
    except GmailProfileValidationError as error:
        logger.warning(
            "Gmail OAuth callback failed stage=gmail_profile outcome=validation_failure "
            "response_mapping=%s email_present=%s email_nonempty_string=%s "
            "normalized_email_valid=%s",
            error.response_is_mapping,
            error.email_present,
            error.email_is_nonempty_string,
            error.normalized_email_valid,
        )
        return _frontend_redirect("failed")
    except GmailProfileError:
        logger.warning("Gmail OAuth callback failed stage=gmail_profile outcome=unknown")
        return _frontend_redirect("failed")
    except FileExistsError, LookupError, ValueError:
        logger.warning("Gmail OAuth callback failed stage=connection_validation")
        return _frontend_redirect("failed")
    except GmailIntegrationNotConfigured:
        logger.warning("Gmail OAuth callback failed stage=credential_encryption_configuration")
        return _frontend_redirect("failed")
    except GmailTransientError:
        logger.warning("Gmail OAuth callback failed stage=google_integration")
        return _frontend_redirect("failed")
    except Exception:
        db.rollback()
        logger.error("Gmail OAuth callback failed stage=credential_persistence")
        return _frontend_redirect("failed")
    return _frontend_redirect("success")


@router.post(
    "/gmail-connections/{connection_id}/sync",
    response_model=GmailSyncResult,
)
def sync_gmail_connection(connection_id: int, current: CsrfUser, db: DbSession) -> GmailSyncResult:
    try:
        return gmail_service.run_manual_sync(db, current, connection_id)
    except GmailReauthorizationRequired as error:
        raise HTTPException(
            status_code=409,
            detail="Google authorization is no longer valid. Reconnect this inbox.",
        ) from error
    except GmailTransientError as error:
        raise HTTPException(
            status_code=503,
            detail="Gmail could not be reached. Try syncing again.",
        ) from error


@router.get(
    "/gmail-connections/{connection_id}/messages",
    response_model=list[GmailMessageListItem],
)
def get_recent_gmail_messages(
    connection_id: int, current: CurrentUser, db: DbSession
) -> list[GmailMessageListItem]:
    return gmail_service.recent_messages(db, current, connection_id)


@router.post(
    "/gmail-connections/{connection_id}/workflow-labels/retry",
    response_model=MessageResponse,
)
def retry_gmail_workflow_labels(
    connection_id: int, current: CsrfUser, db: DbSession
) -> MessageResponse:
    count = gmail_service.retry_connection_labels(db, current, connection_id)
    return MessageResponse(message=f"Queued workflow labels for {count} Gmail threads")


@router.delete(
    "/gmail-connections/{connection_id}",
    response_model=MessageResponse,
)
def disconnect_gmail_connection(
    connection_id: int, current: CsrfUser, db: DbSession
) -> MessageResponse:
    gmail_service.disconnect(db, current, connection_id)
    return MessageResponse(message="Gmail inbox disconnected")
