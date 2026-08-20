import base64
import binascii
from collections.abc import Mapping
from datetime import UTC
from typing import Any, Protocol

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import Settings, get_settings
from app.integrations.gmail.crypto import TokenCipher
from app.integrations.gmail.errors import (
    GmailIntegrationNotConfigured,
    GmailReauthorizationRequired,
    GmailTransientError,
)
from app.integrations.gmail.oauth import GOOGLE_TOKEN_URI
from app.models.organization import GmailOAuthCredential


class GmailMailbox(Protocol):
    def list_messages(self, query: str, page_token: str | None = None) -> Mapping[str, Any]: ...

    def get_metadata(self, message_id: str) -> Mapping[str, Any]: ...

    def get_full_message(self, message_id: str) -> Mapping[str, Any]: ...

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes: ...


class GoogleGmailMailbox:
    def __init__(self, credentials: Credentials):
        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    @staticmethod
    def _execute(request) -> Mapping[str, Any]:
        try:
            return request.execute()
        except HttpError as error:
            if error.resp.status == 401:
                raise GmailReauthorizationRequired(
                    "Google authorization is no longer valid. Reconnect this inbox."
                ) from error
            raise GmailTransientError("Gmail could not be reached. Try syncing again.") from error
        except Exception as error:
            raise GmailTransientError("Gmail could not be reached. Try syncing again.") from error

    def list_messages(self, query: str, page_token: str | None = None) -> Mapping[str, Any]:
        return self._execute(
            self._service.users().messages().list(userId="me", q=query, pageToken=page_token)
        )

    def get_metadata(self, message_id: str) -> Mapping[str, Any]:
        return self._execute(
            self._service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject"],
            )
        )

    def get_full_message(self, message_id: str) -> Mapping[str, Any]:
        return self._execute(
            self._service.users().messages().get(userId="me", id=message_id, format="full")
        )

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        response = self._execute(
            self._service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
        )
        encoded = response.get("data")
        if not isinstance(encoded, str):
            raise GmailTransientError("Gmail attachment data was unavailable.")
        try:
            return base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
            )
        except (binascii.Error, ValueError) as error:
            raise GmailTransientError("Gmail attachment data was unavailable.") from error


def mailbox_from_credential(
    credential: GmailOAuthCredential,
    *,
    settings: Settings | None = None,
    cipher: TokenCipher | None = None,
) -> tuple[GmailMailbox, bool]:
    active_settings = settings or get_settings()
    if not active_settings.gmail_oauth_configured:
        raise GmailIntegrationNotConfigured("Gmail integration is not configured.")
    token_cipher = cipher or TokenCipher.from_settings(active_settings)
    client_id = active_settings.google_oauth_client_id
    client_secret = active_settings.google_oauth_client_secret
    assert client_id is not None and client_secret is not None
    google_expiry = credential.access_token_expires_at
    if google_expiry is not None and google_expiry.tzinfo is not None:
        google_expiry = google_expiry.astimezone(UTC).replace(tzinfo=None)
    credentials = Credentials(
        token=(
            token_cipher.decrypt(credential.encrypted_access_token)
            if credential.encrypted_access_token
            else None
        ),
        refresh_token=token_cipher.decrypt(credential.encrypted_refresh_token),
        token_uri=GOOGLE_TOKEN_URI,
        client_id=client_id.get_secret_value(),
        client_secret=client_secret.get_secret_value(),
        scopes=credential.granted_scopes,
        expiry=google_expiry,
    )
    refreshed = False
    if not credentials.valid:
        if not credentials.refresh_token:
            raise GmailReauthorizationRequired(
                "Google authorization is no longer valid. Reconnect this inbox."
            )
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            raise GmailReauthorizationRequired(
                "Google authorization is no longer valid. Reconnect this inbox."
            ) from error
        except Exception as error:
            raise GmailTransientError("Google authorization could not be refreshed.") from error
        credential.encrypted_access_token = (
            token_cipher.encrypt(credentials.token) if credentials.token else None
        )
        if credentials.refresh_token:
            credential.encrypted_refresh_token = token_cipher.encrypt(credentials.refresh_token)
        refreshed_expiry = credentials.expiry
        if refreshed_expiry is not None and refreshed_expiry.tzinfo is None:
            refreshed_expiry = refreshed_expiry.replace(tzinfo=UTC)
        credential.access_token_expires_at = refreshed_expiry
        refreshed = True
    return GoogleGmailMailbox(credentials), refreshed
