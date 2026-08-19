from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.api.schemas.common import InternalEmail
from app.core.security import normalize_email
from app.models.enums import UserRole


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_login_email(cls, value: str) -> str:
        return normalize_email(value)


class AgencySummary(BaseModel):
    id: int
    name: str
    timezone: str


class UserSummary(BaseModel):
    id: int
    email: InternalEmail
    full_name: str
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    agency: AgencySummary


class AuthResponse(BaseModel):
    user: UserSummary
    csrf_token: str
    environment: str


class MessageResponse(BaseModel):
    message: str
