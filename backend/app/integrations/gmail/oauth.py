import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from os import environ
from urllib.parse import urlencode, urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from email_validator import EmailNotValidError, validate_email
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from oauthlib.oauth2 import (
    InsecureTransportError,
    InvalidClientError,
    InvalidGrantError,
    MismatchingStateError,
)

from app.core.config import Settings, get_settings
from app.integrations.gmail.errors import (
    GmailIntegrationNotConfigured,
    GmailProfileRequestError,
    GmailProfileValidationError,
    GmailTokenExchangeError,
)

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
SAFE_TOKEN_EXCHANGE_REASONS = {
    "insecure_transport",
    "invalid_client",
    "invalid_grant",
    "redirect_uri_mismatch",
    "state_mismatch",
    "scope_change_invalid",
}
PROFILE_REASON_ALIASES = {
    "ACCESSNOTCONFIGURED": "SERVICE_DISABLED",
    "API_DISABLED": "SERVICE_DISABLED",
    "SERVICEDISABLED": "SERVICE_DISABLED",
    "SERVICE_DISABLED": "SERVICE_DISABLED",
    "PERMISSION_DENIED": "PERMISSION_DENIED",
    "FORBIDDEN": "PERMISSION_DENIED",
    "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
    "INSUFFICIENTPERMISSIONS": "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
    "AUTHERROR": "UNAUTHENTICATED",
    "UNAUTHENTICATED": "UNAUTHENTICATED",
    "RATELIMITEXCEEDED": "RATE_LIMITED",
    "RATE_LIMIT_EXCEEDED": "RATE_LIMITED",
    "SERVICE_UNAVAILABLE": "SERVICE_UNAVAILABLE",
}


def _normalized_reason(value: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "", value.upper())


def _safe_profile_http_reason(error: HttpError, status_code: int | None) -> str:
    candidates: list[str] = []
    try:
        payload = json.loads(error.content.decode("utf-8"))
    except AttributeError, UnicodeDecodeError, json.JSONDecodeError:
        payload = None

    def collect(value: object) -> None:
        if isinstance(value, dict):
            reason = value.get("reason")
            if isinstance(reason, str):
                candidates.append(reason)
            for key in ("error", "errors", "details"):
                if key in value:
                    collect(value[key])
            status = value.get("status")
            if isinstance(status, str):
                candidates.append(status)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(payload)
    for candidate in candidates:
        mapped = PROFILE_REASON_ALIASES.get(_normalized_reason(candidate))
        if mapped:
            return mapped
    if status_code == 401:
        return "UNAUTHENTICATED"
    if status_code == 403:
        return "PERMISSION_DENIED"
    if status_code == 429:
        return "RATE_LIMITED"
    if status_code is not None and status_code >= 500:
        return "SERVICE_UNAVAILABLE"
    return "HTTP_ERROR"


@dataclass(frozen=True)
class OAuthTokenSet:
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime | None
    granted_scopes: list[str]
    gmail_address: str


class GoogleOAuthClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        if not self.settings.gmail_oauth_configured:
            raise GmailIntegrationNotConfigured("Gmail integration is not configured.")
        redirect_uri = str(self.settings.google_oauth_redirect_uri)
        if self.settings.environment == "development" and urlparse(redirect_uri).hostname in {
            "localhost",
            "127.0.0.1",
        }:
            environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

    def _flow(self, *, state: str | None = None) -> Flow:
        client_id = self.settings.google_oauth_client_id
        client_secret = self.settings.google_oauth_client_secret
        assert client_id is not None and client_secret is not None
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id.get_secret_value(),
                    "client_secret": client_secret.get_secret_value(),
                    "auth_uri": GOOGLE_AUTH_URI,
                    "token_uri": GOOGLE_TOKEN_URI,
                }
            },
            scopes=[GMAIL_MODIFY_SCOPE],
            state=state,
            autogenerate_code_verifier=False,
        )
        flow.redirect_uri = str(self.settings.google_oauth_redirect_uri)
        return flow

    def authorization_url(self, state: str) -> str:
        url, _ = self._flow(state=state).authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent select_account",
        )
        return url

    @staticmethod
    def _accept_incremental_scope_token(flow: Flow, warning: Warning) -> None:
        """Recover OAuthlib's token when Google returns a valid scope superset."""
        token = getattr(warning, "token", None)
        returned_scope = getattr(warning, "new_scope", None)
        if returned_scope is None and isinstance(token, Mapping):
            returned_scope = token.get("scope")
        if isinstance(returned_scope, str):
            returned_scopes = set(returned_scope.split())
        elif isinstance(returned_scope, list | tuple | set | frozenset):
            returned_scopes = {item for item in returned_scope if isinstance(item, str)}
        else:
            returned_scopes = set()
        if GMAIL_MODIFY_SCOPE not in returned_scopes:
            raise PermissionError(
                "Required Gmail workflow-label scope was not granted"
            ) from warning
        if not isinstance(token, Mapping) or not isinstance(token.get("access_token"), str):
            raise GmailTokenExchangeError("scope_change_invalid") from warning
        flow.oauth2session.token = dict(token)

    def exchange_code(self, code: str) -> OAuthTokenSet:
        flow = self._flow()
        try:
            flow.fetch_token(code=code)
        except Warning as warning:
            self._accept_incremental_scope_token(flow, warning)
        except Exception as error:
            provider_reason = getattr(error, "error", None)
            if provider_reason not in SAFE_TOKEN_EXCHANGE_REASONS:
                if isinstance(error, InsecureTransportError):
                    provider_reason = "insecure_transport"
                elif isinstance(error, InvalidClientError):
                    provider_reason = "invalid_client"
                elif isinstance(error, InvalidGrantError):
                    provider_reason = "invalid_grant"
                elif isinstance(error, MismatchingStateError):
                    provider_reason = "state_mismatch"
                else:
                    provider_reason = "provider_or_network"
            raise GmailTokenExchangeError(provider_reason) from error

        credentials = flow.credentials
        granted_scopes = credentials.granted_scopes
        scopes = sorted(
            set(granted_scopes if granted_scopes is not None else credentials.scopes or [])
        )
        if GMAIL_MODIFY_SCOPE not in scopes:
            raise PermissionError("Required Gmail workflow-label scope was not granted")
        try:
            profile_request = (
                build("gmail", "v1", credentials=credentials, cache_discovery=False)
                .users()
                .getProfile(userId="me")
            )
        except Exception as error:
            raise GmailProfileRequestError(
                status_code=None,
                reason="CLIENT_CONSTRUCTION",
                during_execute=False,
            ) from error
        try:
            profile = profile_request.execute()
        except HttpError as error:
            raw_status = getattr(error.resp, "status", None)
            try:
                status_code = int(raw_status) if raw_status is not None else None
            except TypeError, ValueError:
                status_code = None
            raise GmailProfileRequestError(
                status_code=status_code,
                reason=_safe_profile_http_reason(error, status_code),
                during_execute=True,
            ) from error
        except Exception as error:
            raise GmailProfileRequestError(
                status_code=None,
                reason="CLIENT_OR_NETWORK",
                during_execute=True,
            ) from error

        response_is_mapping = isinstance(profile, Mapping)
        email_present = response_is_mapping and "emailAddress" in profile
        email_value = profile.get("emailAddress") if response_is_mapping else None
        email_is_nonempty_string = isinstance(email_value, str) and bool(email_value.strip())
        normalized_email_valid = False
        normalized_email: str | None = None
        if email_is_nonempty_string:
            try:
                normalized_email = validate_email(
                    email_value, check_deliverability=False
                ).normalized
                normalized_email_valid = True
            except EmailNotValidError:
                normalized_email_valid = False
        if not all(
            (
                response_is_mapping,
                email_present,
                email_is_nonempty_string,
                normalized_email_valid,
            )
        ):
            raise GmailProfileValidationError(
                response_is_mapping=response_is_mapping,
                email_present=email_present,
                email_is_nonempty_string=email_is_nonempty_string,
                normalized_email_valid=normalized_email_valid,
            )
        assert normalized_email is not None
        return OAuthTokenSet(
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            expires_at=credentials.expiry,
            granted_scopes=scopes,
            gmail_address=normalized_email,
        )

    def revoke_token(self, token: str) -> None:
        request = UrlRequest(
            "https://oauth2.googleapis.com/revoke",
            data=urlencode({"token": token}).encode("ascii"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10):
                pass
        except Exception:
            # Local credential deletion is authoritative; revocation is best-effort.
            return


def credentials_from_token_set(tokens: OAuthTokenSet, settings: Settings) -> Credentials:
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    assert client_id is not None and client_secret is not None
    return Credentials(
        token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=client_id.get_secret_value(),
        client_secret=client_secret.get_secret_value(),
        scopes=tokens.granted_scopes,
        expiry=tokens.expires_at,
    )
