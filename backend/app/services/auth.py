from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.security import (
    csrf_token_for_session,
    dummy_password_hash,
    new_session_token,
    normalize_email,
    token_hash,
    verify_password,
)
from app.core.time import utc_now
from app.models.organization import Agency, AuthSession, User

SESSION_TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class AuthContext:
    user: User
    agency: Agency
    session: AuthSession
    csrf_token: str


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    password_hash = user.password_hash if user is not None else dummy_password_hash
    password_valid = verify_password(password, password_hash)
    if user is None or not password_valid or not user.is_active or not user.agency.is_active:
        return None
    return user


def create_session(db: Session, user: User) -> tuple[AuthSession, str, str]:
    settings = get_settings()
    now = utc_now()
    raw_token = new_session_token()
    csrf_token = csrf_token_for_session(raw_token)
    session = AuthSession(
        user_id=user.id,
        token_hash=token_hash(raw_token),
        csrf_token_hash=token_hash(csrf_token),
        created_at=now,
        expires_at=now + timedelta(hours=settings.session_lifetime_hours),
        last_seen_at=now,
    )
    db.add(session)
    db.flush()
    return session, raw_token, csrf_token


def resolve_session(db: Session, raw_token: str) -> AuthContext | None:
    now = utc_now()
    session = db.scalar(
        select(AuthSession)
        .options(joinedload(AuthSession.user).joinedload(User.agency))
        .where(AuthSession.token_hash == token_hash(raw_token))
    )
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= now
        or not session.user.is_active
        or not session.user.agency.is_active
    ):
        return None

    csrf_token = csrf_token_for_session(raw_token)
    if token_hash(csrf_token) != session.csrf_token_hash:
        return None

    if session.last_seen_at <= now - SESSION_TOUCH_INTERVAL:
        db.execute(update(AuthSession).where(AuthSession.id == session.id).values(last_seen_at=now))
        db.commit()
        session.last_seen_at = now
    return AuthContext(
        user=session.user,
        agency=session.user.agency,
        session=session,
        csrf_token=csrf_token,
    )


def revoke_session(session: AuthSession) -> None:
    session.revoked_at = utc_now()
