"""Tenancy API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from synapse_saas.core.pagination import Page


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str | None = Field(None, pattern=r"^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$")


class OrganizationUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    settings: dict[str, object] | None = None


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    status: str
    owner_user_id: uuid.UUID | None
    settings: dict[str, object]
    created_at: datetime


class OrganizationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    role_keys: list[str] = []


class MemberInvite(BaseModel):
    email: EmailStr
    role_keys: list[str] = Field(default_factory=lambda: ["member"])


class MemberUpdate(BaseModel):
    role_keys: list[str] | None = None
    status: str | None = Field(None, pattern=r"^(active|suspended)$")


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID | None
    invited_email: str | None
    email: str | None = None
    display_name: str | None = None
    status: str
    joined_at: datetime | None
    role_keys: list[str] = []
    created_at: datetime


class OrganizationPage(Page[OrganizationRead]):
    pass


class MembershipPage(Page[MembershipRead]):
    pass


class InviteAccept(BaseModel):
    token: str = Field(min_length=10)


class UsageSummaryEntry(BaseModel):
    metric: str
    used: int
    limit: int | None = None
    soft_limit: int | None = None
    within_limit: bool
    soft_limit_breached: bool
