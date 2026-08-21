import secrets
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import token_hash
from app.db.session import get_db_session
from app.models.enums import UserRole
from app.services.auth import AuthContext, resolve_session

DbSession = Annotated[Session, Depends(get_db_session)]


def require_authenticated_user(
    db: DbSession,
    session_token: Annotated[str | None, Cookie(alias=get_settings().session_cookie_name)] = None,
) -> AuthContext:
    if session_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    context = resolve_session(db, session_token)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return context


CurrentUser = Annotated[AuthContext, Depends(require_authenticated_user)]


def require_csrf(
    current: CurrentUser,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthContext:
    if csrf_token is None or not secrets.compare_digest(
        token_hash(csrf_token), current.session.csrf_token_hash
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return current


CsrfUser = Annotated[AuthContext, Depends(require_csrf)]


def require_manager(current: CurrentUser) -> AuthContext:
    if current.user.role is not UserRole.MANAGER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager access required")
    return current


ManagerUser = Annotated[AuthContext, Depends(require_manager)]


def require_manager_csrf(current: CsrfUser) -> AuthContext:
    if current.user.role is not UserRole.MANAGER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager access required")
    return current


ManagerCsrfUser = Annotated[AuthContext, Depends(require_manager_csrf)]


def require_agent(current: CurrentUser) -> AuthContext:
    if current.user.role is not UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent access required")
    return current


AgentUser = Annotated[AuthContext, Depends(require_agent)]
