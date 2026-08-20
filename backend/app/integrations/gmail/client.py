import base64
import binascii
from collections.abc import Mapping
from dataclasses import dataclass
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
    GmailLabelBindingInvalid,
    GmailLabelConflict,
    GmailLabelPermanentError,
    GmailModifyPermissionRequired,
    GmailReauthorizationRequired,
    GmailThreadNotFound,
    GmailTransientError,
)
from app.integrations.gmail.oauth import (
    GMAIL_MODIFY_SCOPE,
    GOOGLE_TOKEN_URI,
    safe_google_http_reason,
)
from app.models.organization import GmailOAuthCredential


@dataclass(frozen=True)
class GmailThreadLabelState:
    any_label_ids: frozenset[str]
    all_label_ids: frozenset[str]
    labelable_message_count: int = 1


class GmailMailbox(Protocol):
    def list_messages(self, query: str, page_token: str | None = None) -> Mapping[str, Any]: ...

    def get_metadata(self, message_id: str) -> Mapping[str, Any]: ...

    def get_full_message(self, message_id: str) -> Mapping[str, Any]: ...

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes: ...

    def list_labels(self) -> Mapping[str, Any]: ...

    def create_label(self, name: str) -> Mapping[str, Any]: ...

    def get_thread_label_state(self, thread_id: str) -> GmailThreadLabelState: ...

    def modify_thread_labels(
        self, thread_id: str, *, add_label_ids: list[str], remove_label_ids: list[str]
    ) -> None: ...


class GoogleGmailMailbox:
    def __init__(self, credentials: Credentials):
        self._can_modify = GMAIL_MODIFY_SCOPE in set(credentials.scopes or [])
        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    @staticmethod
    def _execute(request) -> Mapping[str, Any]:
        try:
            return request.execute()
        except RefreshError as error:
            raise GmailReauthorizationRequired(
                "Google authorization is no longer valid. Reconnect this inbox."
            ) from error
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

    def _require_modify(self) -> None:
        if not self._can_modify:
            raise GmailModifyPermissionRequired(
                "Reconnect Gmail to enable Carrier Hub workflow labels."
            )

    @staticmethod
    def _execute_label(request, *, missing_kind: str | None = None) -> Mapping[str, Any]:
        try:
            return request.execute()
        except RefreshError as error:
            raise GmailReauthorizationRequired(
                "Google authorization is no longer valid. Reconnect this inbox."
            ) from error
        except HttpError as error:
            status = getattr(error.resp, "status", None)
            if status == 401:
                raise GmailReauthorizationRequired(
                    "Google authorization is no longer valid. Reconnect this inbox."
                ) from error
            if status == 403:
                reason = safe_google_http_reason(error, include_status=False)
                if reason in {"RATE_LIMITED", "SERVICE_UNAVAILABLE"}:
                    raise GmailTransientError(
                        "Gmail label delivery is temporarily unavailable."
                    ) from error
                if reason == "UNAUTHENTICATED":
                    raise GmailReauthorizationRequired(
                        "Google authorization is no longer valid. Reconnect this inbox."
                    ) from error
                if reason in {"ACCESS_TOKEN_SCOPE_INSUFFICIENT", "PERMISSION_DENIED"}:
                    raise GmailModifyPermissionRequired(
                        "Reconnect Gmail to enable Carrier Hub workflow labels."
                    ) from error
                raise GmailLabelPermanentError(
                    "Gmail rejected the workflow label request."
                ) from error
            if status == 404 and missing_kind == "label":
                raise GmailLabelBindingInvalid("A managed Gmail label binding is stale.") from error
            if status == 404 and missing_kind == "thread":
                raise GmailThreadNotFound("The Gmail thread is no longer available.") from error
            if status == 409:
                raise GmailLabelConflict("The managed Gmail label already exists.") from error
            if status == 429 or (isinstance(status, int) and status >= 500):
                raise GmailTransientError(
                    "Gmail label delivery is temporarily unavailable."
                ) from error
            raise GmailLabelPermanentError("Gmail rejected the workflow label request.") from error
        except (
            GmailReauthorizationRequired,
            GmailModifyPermissionRequired,
            GmailLabelBindingInvalid,
            GmailThreadNotFound,
            GmailLabelConflict,
            GmailTransientError,
            GmailLabelPermanentError,
        ):
            raise
        except Exception as error:
            raise GmailTransientError("Gmail label delivery is temporarily unavailable.") from error

    def list_labels(self) -> Mapping[str, Any]:
        self._require_modify()
        return self._execute_label(self._service.users().labels().list(userId="me"))

    def create_label(self, name: str) -> Mapping[str, Any]:
        self._require_modify()
        return self._execute_label(
            self._service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
        )

    def get_thread_label_state(self, thread_id: str) -> GmailThreadLabelState:
        self._require_modify()
        response = self._execute_label(
            self._service.users().threads().get(userId="me", id=thread_id, format="minimal"),
            missing_kind="thread",
        )
        if not isinstance(response, Mapping):
            raise GmailTransientError("Gmail returned an invalid thread response.")
        raw_messages = response.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            raise GmailTransientError("Gmail returned an invalid thread response.")

        per_message: list[set[str]] = []
        for message in raw_messages:
            if not isinstance(message, Mapping):
                raise GmailTransientError("Gmail returned an invalid thread response.")
            raw_label_ids = message.get("labelIds", [])
            if not isinstance(raw_label_ids, list) or any(
                not isinstance(label_id, str) or not label_id for label_id in raw_label_ids
            ):
                raise GmailTransientError("Gmail returned an invalid thread response.")
            label_ids = set(raw_label_ids)
            if "DRAFT" in label_ids:
                continue
            per_message.append(label_ids)

        if not per_message:
            return GmailThreadLabelState(frozenset(), frozenset(), 0)
        any_label_ids = set().union(*per_message)
        all_label_ids = set(per_message[0]).intersection(*per_message[1:])
        return GmailThreadLabelState(
            frozenset(any_label_ids),
            frozenset(all_label_ids),
            len(per_message),
        )

    def modify_thread_labels(
        self, thread_id: str, *, add_label_ids: list[str], remove_label_ids: list[str]
    ) -> None:
        self._require_modify()
        self._execute_label(
            self._service.users()
            .threads()
            .modify(
                userId="me",
                id=thread_id,
                body={"addLabelIds": add_label_ids, "removeLabelIds": remove_label_ids},
            ),
            missing_kind="thread",
        )


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
