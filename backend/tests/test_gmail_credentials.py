from datetime import timedelta

from app.core.time import utc_now
from app.integrations.gmail import client as gmail_client
from app.integrations.gmail.crypto import TokenCipher
from app.models.organization import GmailOAuthCredential


def test_expired_access_token_refreshes_and_is_reencrypted(configured_google, monkeypatch) -> None:
    cipher = TokenCipher.from_settings()
    credential = GmailOAuthCredential(
        gmail_connection_id=1,
        encrypted_access_token=cipher.encrypt("expired-access-token"),
        encrypted_refresh_token=cipher.encrypt("valid-refresh-token"),
        access_token_expires_at=utc_now() - timedelta(minutes=1),
        granted_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )

    def fake_refresh(credentials, request) -> None:
        credentials.token = "fresh-access-token"
        credentials.expiry = utc_now() + timedelta(hours=1)
        credentials._refresh_token = "rotated-refresh-token"

    mailbox_marker = object()
    monkeypatch.setattr(gmail_client.Credentials, "refresh", fake_refresh)
    monkeypatch.setattr(gmail_client, "GoogleGmailMailbox", lambda credentials: mailbox_marker)

    mailbox, refreshed = gmail_client.mailbox_from_credential(credential, cipher=cipher)
    assert mailbox is mailbox_marker
    assert refreshed is True
    assert cipher.decrypt(credential.encrypted_access_token or "") == "fresh-access-token"
    assert cipher.decrypt(credential.encrypted_refresh_token) == "rotated-refresh-token"
    assert "fresh-access-token" not in (credential.encrypted_access_token or "")
    assert "rotated-refresh-token" not in credential.encrypted_refresh_token
