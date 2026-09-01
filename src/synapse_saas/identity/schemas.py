"""Identity API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

PASSWORD_MIN_LENGTH = 10


class PasswordStr(str):
    """String that enforces the minimum password policy at parse time."""


def validate_password(v: str) -> str:
    if len(v) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    return v


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str = Field(min_length=1, max_length=200)

    _pw = field_validator("password")(validate_password)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str | None = None  # also accepted via httpOnly cookie


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str
    avatar_url: str | None
    is_platform_admin: bool
    is_active: bool
    last_login_at: datetime | None


class UserWithOrgs(UserRead):
    orgs: list[OrgSummary] = []


class OrgSummary(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    role_keys: list[str] = []


class AuthResponse(BaseModel):
    user: UserRead
    tokens: TokenPair


class SwitchOrgRequest(BaseModel):
    organization_id: uuid.UUID


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    _pw = field_validator("password")(validate_password)
