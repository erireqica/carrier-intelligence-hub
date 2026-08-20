import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations.gmail.client import GoogleGmailMailbox, mailbox_from_credential
from app.integrations.gmail.crypto import TokenCipher
from app.integrations.gmail.errors import GmailTransientError
from app.models.organization import GmailOAuthCredential


class FakeRequest:
    def __init__(self, response: dict) -> None:
        self.response = response

    def execute(self) -> dict:
        return self.response


class FakeAttachments:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    def get(self, **kwargs) -> FakeRequest:
        self.calls.append(kwargs)
        return FakeRequest(self.response)


def mailbox_with_attachment_response(response: dict):
    attachments = FakeAttachments(response)
    messages = SimpleNamespace(attachments=lambda: attachments)
    users = SimpleNamespace(messages=lambda: messages)
    mailbox = GoogleGmailMailbox.__new__(GoogleGmailMailbox)
    mailbox._service = SimpleNamespace(users=lambda: users)
    return mailbox, attachments


def test_get_attachment_uses_read_only_attachment_endpoint_and_decodes_base64url() -> None:
    expected = b"synthetic-pdf-bytes"
    encoded = base64.urlsafe_b64encode(expected).decode().rstrip("=")
    mailbox, attachments = mailbox_with_attachment_response({"data": encoded})

    assert mailbox.get_attachment("message-1", "attachment-1") == expected
    assert attachments.calls == [{"userId": "me", "messageId": "message-1", "id": "attachment-1"}]


@pytest.mark.parametrize("response", [{}, {"data": 42}, {"data": "%%%"}])
def test_get_attachment_rejects_missing_or_malformed_data(response: dict) -> None:
    mailbox, _ = mailbox_with_attachment_response(response)

    with pytest.raises(GmailTransientError, match="unavailable"):
        mailbox.get_attachment("message-1", "attachment-1")


def test_mailbox_refreshes_expired_access_token_and_persists_encrypted_value(
    monkeypatch,
) -> None:
    key = Fernet.generate_key().decode()
    settings = Settings(
        google_oauth_client_id=SecretStr("synthetic-client"),
        google_oauth_client_secret=SecretStr("synthetic-secret"),
        google_token_encryption_key=SecretStr(key),
    )
    cipher = TokenCipher.from_settings(settings)
    credential = GmailOAuthCredential(
        gmail_connection_id=1,
        encrypted_access_token=cipher.encrypt("expired-access"),
        encrypted_refresh_token=cipher.encrypt("synthetic-refresh"),
        access_token_expires_at=datetime.now(UTC) - timedelta(minutes=5),
        granted_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )

    def refresh(credentials, request) -> None:
        credentials.token = "refreshed-access"
        credentials.expiry = datetime.now(UTC) + timedelta(hours=1)

    monkeypatch.setattr("app.integrations.gmail.client.Credentials.refresh", refresh)
    monkeypatch.setattr(
        "app.integrations.gmail.client.GoogleGmailMailbox",
        lambda credentials: SimpleNamespace(credentials=credentials),
    )

    mailbox, refreshed = mailbox_from_credential(credential, settings=settings, cipher=cipher)

    assert refreshed is True
    assert mailbox.credentials.token == "refreshed-access"
    assert cipher.decrypt(credential.encrypted_access_token) == "refreshed-access"
    assert cipher.decrypt(credential.encrypted_refresh_token) == "synthetic-refresh"
