from datetime import timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.time import utc_now
from app.integrations.gmail.crypto import TokenCipher
from app.integrations.gmail.sync import SyncResult
from app.models.enums import GmailConnectionStatus, UserRole
from app.models.organization import (
    Agency,
    GmailConnection,
    GmailOAuthCredential,
    User,
)
from app.services import gmail as gmail_service


class FakeRevoker:
    def __init__(self) -> None:
        self.revoked: list[str] = []

    def revoke_token(self, token: str) -> None:
        self.revoked.append(token)


def add_connection(
    db: Session,
    owner: User,
    address: str,
    *,
    credential: bool = False,
) -> GmailConnection:
    connection = GmailConnection(
        agency_id=owner.agency_id,
        user_id=owner.id,
        gmail_address=address,
        status=GmailConnectionStatus.CONNECTED,
        connected_at=utc_now(),
    )
    db.add(connection)
    db.flush()
    if credential:
        cipher = TokenCipher.from_settings()
        db.add(
            GmailOAuthCredential(
                gmail_connection_id=connection.id,
                encrypted_access_token=cipher.encrypt("access-for-revocation"),
                encrypted_refresh_token=cipher.encrypt("refresh-for-revocation"),
                access_token_expires_at=utc_now() + timedelta(hours=1),
                granted_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            )
        )
    db.commit()
    return connection


def test_unconfigured_state_does_not_break_connection_listing(
    client: TestClient, login, monkeypatch
) -> None:
    monkeypatch.setattr(
        gmail_service,
        "get_settings",
        lambda: SimpleNamespace(gmail_oauth_configured=False),
    )
    login(client, "agent.one@demo.local")
    response = client.get("/api/v1/gmail-connections")
    assert response.status_code == 200
    assert response.json() == {"configured": False, "connections": []}


def test_agent_manager_and_cross_agency_connection_permissions(
    client: TestClient,
    db: Session,
    login,
    configured_google,
    monkeypatch,
) -> None:
    agent_one = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    agent_two = db.scalar(select(User).where(User.email == "agent.two@demo.local"))
    assert agent_one is not None and agent_two is not None
    own = add_connection(db, agent_one, "agent-one-stage3@gmail.com")
    other = add_connection(db, agent_two, "agent-two-stage3@gmail.com")

    other_agency = Agency(name="Other Agency", timezone="UTC", is_active=True)
    db.add(other_agency)
    db.flush()
    outsider = User(
        agency_id=other_agency.id,
        email="outsider@demo.local",
        full_name="Outside User",
        role=UserRole.AGENT,
        password_hash=hash_password("synthetic-password"),
        is_active=True,
    )
    db.add(outsider)
    db.flush()
    outside_connection = add_connection(db, outsider, "outside-stage3@gmail.com")

    agent_auth = login(client, agent_one.email)
    listed = client.get("/api/v1/gmail-connections").json()["connections"]
    assert [item["id"] for item in listed] == [own.id]
    assert client.get(f"/api/v1/gmail-connections/{other.id}/messages").status_code == 404
    assert (
        client.post(
            f"/api/v1/gmail-connections/{other.id}/sync",
            headers={"X-CSRF-Token": agent_auth["csrf_token"]},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/gmail-connections/{other.id}",
            headers={"X-CSRF-Token": agent_auth["csrf_token"]},
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/gmail-connections/{outside_connection.id}/messages").status_code == 404
    )

    monkeypatch.setattr(
        gmail_service,
        "sync_connection",
        lambda db, connection_id: SyncResult(connection_id=connection_id),
    )
    manager_auth = login(client, "manager@demo.local")
    manager_list = client.get("/api/v1/gmail-connections").json()["connections"]
    assert {item["id"] for item in manager_list} == {own.id, other.id}
    manager_sync = client.post(
        f"/api/v1/gmail-connections/{other.id}/sync",
        headers={"X-CSRF-Token": manager_auth["csrf_token"]},
    )
    assert manager_sync.status_code == 200
    assert (
        client.delete(
            f"/api/v1/gmail-connections/{other.id}",
            headers={"X-CSRF-Token": manager_auth["csrf_token"]},
        ).status_code
        == 404
    )


def test_disconnect_removes_local_credentials_even_when_revocation_is_best_effort(
    client: TestClient,
    db: Session,
    login,
    configured_google,
    monkeypatch,
) -> None:
    owner = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert owner is not None
    connection = add_connection(db, owner, "disconnect-stage3@gmail.com", credential=True)
    fake = FakeRevoker()
    monkeypatch.setattr(gmail_service, "GoogleOAuthClient", lambda: fake)
    auth = login(client, owner.email)
    response = client.delete(
        f"/api/v1/gmail-connections/{connection.id}",
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert response.status_code == 200
    db.refresh(connection)
    assert connection.status is GmailConnectionStatus.DISCONNECTED
    assert (
        db.scalar(
            select(func.count())
            .select_from(GmailOAuthCredential)
            .where(GmailOAuthCredential.gmail_connection_id == connection.id)
        )
        == 0
    )
    assert fake.revoked == ["refresh-for-revocation"]
