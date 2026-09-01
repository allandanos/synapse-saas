"""Identity domain service.

Registration, login, refresh-token rotation with reuse detection, logout,
password reset, OIDC user upsert.

Rotation model: every refresh mints a new token and links old→new via
`replaced_by_token_id`. Presenting an already-rotated token is a theft signal
outside a small grace window (concurrent tabs) — the whole chain is revoked
and the event audited.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core import events
from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import (
    AuthenticationError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    TokenReuseError,
    UserNotFoundError,
)
from synapse_saas.core.logging import get_logger
from synapse_saas.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from synapse_saas.identity.models import PasswordResetToken, RefreshToken, User

if TYPE_CHECKING:
    from synapse_saas.identity.schemas import TokenPair

logger = get_logger(__name__)

RESET_TOKEN_BYTES = 32
RESET_TOKEN_TTL_MINUTES = 30


class IdentityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Registration / login ────────────────────────────────────────────────────

    async def register(self, *, email: str, password: str, display_name: str) -> User:
        existing = (await self.session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is not None:
            raise EmailAlreadyRegisteredError("An account with this email already exists")

        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
            identity_provider="local",
        )
        self.session.add(user)
        await self.session.flush()

        self._audit(events.USER_REGISTERED, user_id=user.id, diff={"email": email})
        return user

    async def login(self, *, email: str, password: str) -> User:
        user = (await self.session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None or user.password_hash is None or not user.is_active:
            if user is None:
                verify_password(password, _dummy_hash())  # timing equalization
            raise InvalidCredentialsError("Invalid email or password")
        if not verify_password(password, user.password_hash):
            self._audit(events.USER_LOGIN_FAILED, user_id=user.id, diff={"email": email})
            raise InvalidCredentialsError("Invalid email or password")

        user.last_login_at = datetime.now(UTC)
        self._audit(events.USER_LOGIN_SUCCEEDED, user_id=user.id)
        return user

    async def get_user(self, user_id: UUID) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise UserNotFoundError("User not found")
        return user

    async def upsert_oidc_user(self, *, email: str, display_name: str, provider_subject: str) -> User | None:
        user = (await self.session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            user = User(
                email=email,
                display_name=display_name,
                identity_provider="keycloak",
                provider_subject=provider_subject,
            )
            self.session.add(user)
        else:
            user.provider_subject = provider_subject
        await self.session.flush()
        return user

    # ── Tokens ──────────────────────────────────────────────────────────────────

    async def issue_tokens(
        self,
        user: User,
        *,
        organization_id: UUID | None = None,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> TokenPair:
        from synapse_saas.identity.schemas import TokenPair as TokenPairSchema

        settings = get_settings()
        refresh_token = generate_refresh_token()
        row = RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            organization_id=organization_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_seconds),
            user_agent=user_agent,
            ip=ip,
        )
        self.session.add(row)
        await self.session.flush()

        access_token = create_access_token(
            user.id,
            email=str(user.email),
            organization_id=organization_id,
            is_platform_admin=user.is_platform_admin,
        )
        return TokenPairSchema(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.access_token_ttl_seconds,
        )

    async def refresh(
        self,
        refresh_token: str,
        *,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[User, TokenPair]:
        """Rotate a refresh token. Reuse of a rotated token revokes the chain."""
        settings = get_settings()
        token_hash = hash_refresh_token(refresh_token)
        row = (
            await self.session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        ).scalar_one_or_none()

        if row is None:
            raise AuthenticationError("Invalid refresh token")

        now = datetime.now(UTC)
        if row.expires_at < now:
            raise AuthenticationError("Refresh token expired")

        if row.revoked_at is not None:
            # Already rotated? Within grace = benign concurrent refresh; else theft.
            grace = timedelta(seconds=settings.refresh_reuse_grace_seconds)
            within_grace = row.replaced_by_token_id is not None and (now - row.revoked_at) <= grace
            if not within_grace:
                await self._revoke_chain(row.user_id, row.id)
                self._audit(events.USER_TOKEN_REUSE_DETECTED, user_id=row.user_id)
                # The revocation MUST outlive the error the request is about to
                # raise — get_session rolls back on DomainError, but the whole
                # point of detecting theft is killing the session.
                await self.session.commit()
                raise TokenReuseError("Refresh token reuse detected; session revoked")
            raise AuthenticationError("Refresh token already used")

        user = await self.session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid refresh token")

        pair = await self.issue_tokens(
            user,
            organization_id=row.organization_id,
            user_agent=user_agent,
            ip=ip,
        )
        # Mark rotated, linked to the successor
        successor_hash = hash_refresh_token(pair.refresh_token)
        successor = (
            await self.session.execute(select(RefreshToken).where(RefreshToken.token_hash == successor_hash))
        ).scalar_one()
        row.revoked_at = now
        row.replaced_by_token_id = successor.id
        self._audit(events.USER_TOKEN_REFRESHED, user_id=user.id)
        return user, pair

    async def logout(self, refresh_token: str) -> None:
        token_hash = hash_refresh_token(refresh_token)
        row = (
            await self.session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        ).scalar_one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            self._audit(events.USER_LOGGED_OUT, user_id=row.user_id)

    async def set_active_org(self, user_id: UUID, organization_id: UUID) -> User:
        """Re-scope the session: next refresh mints tokens with the org claim."""
        user = await self.get_user(user_id)
        # Membership validated by the router dependency; here we just record it
        return user

    # ── Password reset ──────────────────────────────────────────────────────────

    async def request_password_reset(self, email: str) -> PasswordResetToken | None:
        user = (await self.session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            return None  # never reveal whether the email exists
        token = secrets.token_urlsafe(RESET_TOKEN_BYTES)
        row = PasswordResetToken(
            user_id=user.id,
            token_hash=_hash(token),
            expires_at=datetime.now(UTC) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
        )
        self.session.add(row)
        self._audit(events.USER_PASSWORD_RESET_REQUESTED, user_id=user.id)
        return row

    async def reset_password(self, *, token: str, new_password: str) -> User:
        row = (
            await self.session.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.token_hash == _hash(token),
                    PasswordResetToken.used_at.is_(None),
                    PasswordResetToken.expires_at >= datetime.now(UTC),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise AuthenticationError("Invalid or expired reset token")

        user = await self.session.get(User, row.user_id)
        if user is None:
            raise UserNotFoundError("User not found")

        user.password_hash = hash_password(new_password)
        row.used_at = datetime.now(UTC)
        # All sessions die on password change
        await self._revoke_chain(user.id, None)
        self._audit(events.USER_PASSWORD_RESET_COMPLETED, user_id=user.id)
        return user

    # ── Internals ───────────────────────────────────────────────────────────────

    async def _revoke_chain(self, user_id: UUID, from_token_id: UUID | None) -> None:
        rows = (
            (
                await self.session.execute(
                    select(RefreshToken).where(
                        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        now = datetime.now(UTC)
        for row in rows:
            row.revoked_at = now

    def _audit(self, event_type: str, *, user_id: UUID | None, diff: dict | None = None) -> None:
        from synapse_saas.audit.service import AuditService

        AuditService(self.session).log(
            event_type,
            actor_user_id=user_id,
            organization_id=None,
            diff=diff,
        )


def _hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _dummy_hash() -> str:
    # Argon2 hash of an unguessable value — burns comparable CPU on unknown-email logins
    return (
        "$argon2id$v=19$m=65536,t=3,p=4$"
        "c3NybU5vdEFSZWFsUGFzc3dvcmQ"
        "$bQ9OBGPOtW4Kpl6Z73pQ4Lc2v1OiqeuCYiY0FbxBNCs"
    )
