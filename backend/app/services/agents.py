from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.schemas.domain import AgentCreateInput
from app.core.security import hash_password
from app.core.time import utc_now
from app.models.enums import GmailConnectionStatus, UserRole
from app.models.operations import PolicyCase
from app.models.organization import AuthSession, GmailConnection, User
from app.services.audit import record_audit_event
from app.services.auth import AuthContext


def _managed_agent(db: Session, current: AuthContext, agent_id: int) -> User:
    agent = db.scalar(
        select(User).where(
            User.id == agent_id,
            User.agency_id == current.user.agency_id,
            User.role == UserRole.AGENT,
            User.removed_at.is_(None),
        )
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _stop_access(db: Session, agent: User) -> int:
    now = utc_now()
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == agent.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    connections = db.scalars(
        select(GmailConnection)
        .options(joinedload(GmailConnection.oauth_credential))
        .where(
            GmailConnection.user_id == agent.id,
            GmailConnection.status != GmailConnectionStatus.DISCONNECTED,
        )
    ).all()
    for connection in connections:
        if connection.oauth_credential is not None:
            db.delete(connection.oauth_credential)
        connection.status = GmailConnectionStatus.DISCONNECTED
        connection.last_error_summary = None
    return len(connections)


def create_agent(db: Session, current: AuthContext, data: AgentCreateInput) -> User:
    agent = User(
        agency_id=current.user.agency_id,
        full_name=data.full_name,
        email=data.email,
        role=UserRole.AGENT,
        password_hash=hash_password(data.initial_password),
        is_active=True,
    )
    db.add(agent)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="That login email is already in use."
        ) from error
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="AGENT_CREATED",
        description=f"{current.user.full_name} created Agent {agent.full_name}",
        metadata={"agent_id": agent.id},
    )
    db.commit()
    db.refresh(agent)
    return agent


def set_agent_enabled(
    db: Session, current: AuthContext, agent_id: int, *, is_enabled: bool
) -> User:
    agent = _managed_agent(db, current, agent_id)
    disconnected = 0
    agent.is_active = is_enabled
    if not is_enabled:
        disconnected = _stop_access(db, agent)
    event_type = "AGENT_ENABLED" if is_enabled else "AGENT_DISABLED"
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type=event_type,
        description=(
            f"{current.user.full_name} "
            f"{event_type.removeprefix('AGENT_').lower()} Agent {agent.full_name}"
        ),
        metadata={"agent_id": agent.id, "gmail_connections_disconnected": disconnected},
    )
    db.commit()
    db.refresh(agent)
    return agent


def remove_agent(db: Session, current: AuthContext, agent_id: int) -> None:
    agent = _managed_agent(db, current, agent_id)
    active_cases = (
        db.scalar(
            select(func.count())
            .select_from(PolicyCase)
            .where(
                PolicyCase.agency_id == current.user.agency_id,
                PolicyCase.assigned_agent_id == agent.id,
                PolicyCase.dismissed_at.is_(None),
            )
        )
        or 0
    )
    if active_cases:
        raise HTTPException(
            status_code=409,
            detail="Reassign this Agent's active Cases before removing the account.",
        )
    agent.is_active = False
    agent.removed_at = utc_now()
    disconnected = _stop_access(db, agent)
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="AGENT_REMOVED",
        description=f"{current.user.full_name} removed Agent {agent.full_name}",
        metadata={"agent_id": agent.id, "gmail_connections_disconnected": disconnected},
    )
    db.commit()
