from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import token_hash
from app.core.time import utc_now
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
