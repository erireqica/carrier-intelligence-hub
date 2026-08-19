from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import CsrfUser, CurrentUser, DbSession
from app.api.schemas.auth import (
    AgencySummary,
    AuthResponse,
    LoginRequest,
    MessageResponse,
    UserSummary,
)
from app.core.config import get_settings
from app.core.time import utc_now
from app.services.audit import record_audit_event
from app.services.auth import authenticate_user, create_session, revoke_session

router = APIRouter(prefix="/auth", tags=["authentication"])


def auth_response(current_user, csrf_token: str) -> AuthResponse:
    settings = get_settings()
    return AuthResponse(
        user=UserSummary(
            id=current_user.id,
            email=current_user.email,
            full_name=current_user.full_name,
            role=current_user.role,
            is_active=current_user.is_active,
            last_login_at=current_user.last_login_at,
            agency=AgencySummary(
                id=current_user.agency.id,
                name=current_user.agency.name,
                timezone=current_user.agency.timezone,
            ),
        ),
        csrf_token=csrf_token,
        environment=settings.environment,
    )


@router.post("/login", response_model=AuthResponse)
def login(data: LoginRequest, response: Response, db: DbSession) -> AuthResponse:
    user = authenticate_user(db, str(data.email), data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    _, raw_token, csrf_token = create_session(db, user)
    user.last_login_at = utc_now()
    record_audit_event(
        db,
        agency_id=user.agency_id,
        actor_user_id=user.id,
        event_type="USER_LOGIN",
        description=f"{user.full_name} signed in",
    )
    db.commit()
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_lifetime_hours * 60 * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return auth_response(user, csrf_token)


@router.get("/me", response_model=AuthResponse)
def me(current: CurrentUser, db: DbSession) -> AuthResponse:
    db.commit()
    return auth_response(current.user, current.csrf_token)


@router.post("/logout", response_model=MessageResponse)
def logout(current: CsrfUser, response: Response, db: DbSession) -> MessageResponse:
    revoke_session(current.session)
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="USER_LOGOUT",
        description=f"{current.user.full_name} signed out",
    )
    db.commit()
    settings = get_settings()
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    return MessageResponse(message="Signed out")
