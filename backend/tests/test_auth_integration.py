from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import token_hash
from app.core.time import utc_now
from app.models.audit import AuditEvent
from app.models.enums import UserRole
from app.models.organization import AuthSession, User
from app.services import auth as auth_service

TEST_PASSWORD = "demo-test-password"


def test_login_me_logout_and_hashed_session(client: TestClient, db: Session, login) -> None:
    auth = login(client, "MANAGER@DEMO.LOCAL")
    assert auth["user"]["role"] == UserRole.MANAGER
    assert auth["csrf_token"]

    cookie_name = get_settings().session_cookie_name
    raw_token = client.cookies.get(cookie_name)
    assert raw_token
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(raw_token)))
    assert session is not None
    assert session.token_hash != raw_token
    assert raw_token not in session.csrf_token_hash

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "manager@demo.local"

    logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": auth["csrf_token"]})
    assert logout.status_code == 200
    db.refresh(session)
    assert session.revoked_at is not None
    assert client.get("/api/v1/auth/me").status_code == 401


def test_agent_and_manager_can_set_and_clear_validated_display_timezones(
    client: TestClient, db: Session, login
) -> None:
    agent_auth = login(client, "agent.one@demo.local")
    assert agent_auth["user"]["timezone"] is None
    assert agent_auth["user"]["agency"]["timezone"] == "America/Chicago"
    agent_headers = {"X-CSRF-Token": agent_auth["csrf_token"]}

    updated_agent = client.patch(
        "/api/v1/auth/profile",
        json={
            "full_name": agent_auth["user"]["full_name"],
            "email": agent_auth["user"]["email"],
            "timezone": "Europe/Belgrade",
        },
        headers=agent_headers,
    )
    assert updated_agent.status_code == 200
    assert updated_agent.json()["user"]["timezone"] == "Europe/Belgrade"
    assert client.get("/api/v1/auth/me").json()["user"]["timezone"] == "Europe/Belgrade"

    agent = db.get(User, agent_auth["user"]["id"])
    assert agent is not None and agent.timezone == "Europe/Belgrade"
    profile_event = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.actor_user_id == agent.id,
            AuditEvent.event_type == "PROFILE_UPDATED",
        )
        .order_by(AuditEvent.id.desc())
    )
    assert profile_event is not None
    assert profile_event.event_metadata["changed_fields"] == ["timezone"]

    invalid = client.patch(
        "/api/v1/auth/profile",
        json={
            "full_name": agent.full_name,
            "email": agent.email,
            "timezone": "Mars/Olympus_Mons",
        },
        headers=agent_headers,
    )
    assert invalid.status_code == 422
    assert "Select a valid IANA timezone." in invalid.json()["detail"][0]["msg"]
    db.refresh(agent)
    assert agent.timezone == "Europe/Belgrade"

    cleared = client.patch(
        "/api/v1/auth/profile",
        json={
            "full_name": agent.full_name,
            "email": agent.email,
            "timezone": "",
        },
        headers=agent_headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["user"]["timezone"] is None

    manager_auth = login(client, "manager@demo.local")
    manager_headers = {"X-CSRF-Token": manager_auth["csrf_token"]}
    updated_manager = client.patch(
        "/api/v1/auth/profile",
        json={
            "full_name": manager_auth["user"]["full_name"],
            "email": manager_auth["user"]["email"],
            "timezone": "UTC",
        },
        headers=manager_headers,
    )
    assert updated_manager.status_code == 200
    assert updated_manager.json()["user"]["timezone"] == "UTC"

    preserved = client.patch(
        "/api/v1/auth/profile",
        json={
            "full_name": "Morgan Reed Updated",
            "email": manager_auth["user"]["email"],
        },
        headers=manager_headers,
    )
    assert preserved.status_code == 200
    assert preserved.json()["user"]["timezone"] == "UTC"


def test_invalid_disabled_expired_and_revoked_sessions(
    client: TestClient, db: Session, login
) -> None:
    invalid_password = client.post(
        "/api/v1/auth/login",
        json={"email": "agent.one@demo.local", "password": "wrong-password"},
    )
    nonexistent = client.post(
        "/api/v1/auth/login",
        json={"email": "missing@demo.local", "password": "wrong-password"},
    )
    assert invalid_password.status_code == nonexistent.status_code == 401
    assert invalid_password.json() == nonexistent.json() == {"detail": "Invalid email or password"}

    disabled = db.scalar(select(User).where(User.email == "agent.two@demo.local"))
    assert disabled is not None
    disabled.is_active = False
    db.commit()
    denied = client.post(
        "/api/v1/auth/login",
        json={"email": disabled.email, "password": TEST_PASSWORD},
    )
    assert denied.status_code == 401

    auth = login(client, "agent.one@demo.local")
    assert auth["user"]["role"] == UserRole.AGENT
    session = db.scalar(select(AuthSession).order_by(AuthSession.id.desc()))
    assert session is not None
    session.expires_at = utc_now() - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401

    login(client, "agent.one@demo.local")
    session = db.scalar(select(AuthSession).order_by(AuthSession.id.desc()))
    assert session is not None
    session.revoked_at = utc_now()
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_disabling_user_invalidates_an_existing_session(
    client: TestClient, db: Session, login
) -> None:
    login(client, "agent.one@demo.local")
    user = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert user is not None
    user.is_active = False
    db.commit()
    assert client.get("/api/v1/dashboard").status_code == 401


def test_session_activity_is_persisted_and_throttled(
    client: TestClient, db: Session, login, monkeypatch
) -> None:
    login(client, "agent.one@demo.local")
    session = db.scalar(select(AuthSession).order_by(AuthSession.id.desc()))
    assert session is not None

    now = utc_now()
    old_last_seen = now - auth_service.SESSION_TOUCH_INTERVAL - timedelta(seconds=1)
    session.last_seen_at = old_last_seen
    db.commit()
    monkeypatch.setattr(auth_service, "utc_now", lambda: now)

    assert client.get("/api/v1/dashboard").status_code == 200
    db.expire(session, ["last_seen_at"])
    assert session.last_seen_at == now

    recent_last_seen = now - timedelta(minutes=1)
    session.last_seen_at = recent_last_seen
    db.commit()
    assert client.get("/api/v1/cases").status_code == 200
    db.expire(session, ["last_seen_at"])
    assert session.last_seen_at == recent_last_seen
