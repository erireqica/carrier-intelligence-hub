from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

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


class ProfileUpdateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    current_password: str | None = Field(default=None, min_length=8, max_length=256)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Full name must contain at least two characters")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_profile_email(cls, value: str) -> str:
        return normalize_email(value)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)
    confirm_new_password: str = Field(min_length=12, max_length=256)

    @model_validator(mode="after")
    def passwords_match(self) -> PasswordChangeRequest:
        if self.new_password != self.confirm_new_password:
            raise ValueError("New passwords do not match")
        return self


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
