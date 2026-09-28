"""Auth endpoints."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse

from synapse_saas.core.cache import VersionedCache
from synapse_saas.core.config import get_settings
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.identity.provider import get_identity_provider
from synapse_saas.identity.schemas import (
    AccessTokenResponse,
    AuthResponse,
    ForgotPasswordRequest,
    InviteAcceptRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SwitchOrgRequest,
    TokenPair,
    UserRead,
    UserWithOrgs,
)
from synapse_saas.identity.service import IdentityService
from synapse_saas.tenancy.repository import MembershipRepository

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "synapse_rt"
OIDC_STATE_TTL_SECONDS = 600


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure_effective,
        max_age=settings.refresh_token_ttl_seconds,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/")


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, response: Response, session: SessionDep) -> AuthResponse:
    service = IdentityService(session)
    user = await service.register(
        email=str(body.email), password=body.password, display_name=body.display_name
    )
    tokens = await service.issue_tokens(user, user_agent=None, ip=None)
    _set_refresh_cookie(response, tokens.refresh_token)
    return AuthResponse(user=UserRead.model_validate(user), tokens=tokens)


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, session: SessionDep
) -> AuthResponse:
    service = IdentityService(session)
    user = await service.login(email=str(body.email), password=body.password)
    tokens = await service.issue_tokens(
        user,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    _set_refresh_cookie(response, tokens.refresh_token)
    return AuthResponse(user=UserRead.model_validate(user), tokens=tokens)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    request: Request,
    response: Response,
    session: SessionDep,
) -> TokenPair:
    token = body.refresh_token or request.cookies.get(REFRESH_COOKIE)
    if not token:
        from synapse_saas.core.errors import AuthenticationError

        raise AuthenticationError("Missing refresh token")
    service = IdentityService(session)
    _, tokens = await service.refresh(
        token,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    _set_refresh_cookie(response, tokens.refresh_token)
    return tokens


# ── OIDC (Keycloak) — authorization-code flow with PKCE ───────────────────────
# The browser never sees tokens in a URL: the callback sets the refresh cookie
# and bounces to the console, which mints an access token through /auth/refresh.

_oidc_state = VersionedCache("oidc", ttl=OIDC_STATE_TTL_SECONDS)


def _safe_return_to(raw: str | None) -> str:
    """Only same-origin paths — never an open redirect."""
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return "/dashboard"


def _callback_uri(request: Request) -> str:
    settings = get_settings()
    if settings.oidc_redirect_uri:
        return settings.oidc_redirect_uri
    return str(request.url_for("oidc_callback"))


@router.get("/oidc/start", status_code=status.HTTP_302_FOUND, response_class=RedirectResponse)
async def oidc_start(request: Request, return_to: str | None = None) -> RedirectResponse:
    """Start an SSO login: PKCE verifier + nonce are kept server-side under an
    opaque `state` for OIDC_STATE_TTL_SECONDS; the browser is sent to the IdP."""
    provider = get_identity_provider()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    nonce = secrets.token_urlsafe(16)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    await _oidc_state.set(
        state, json.dumps({"verifier": verifier, "nonce": nonce, "return_to": _safe_return_to(return_to)})
    )
    url = provider.authorization_url(
        redirect_uri=_callback_uri(request), state=state, nonce=nonce, code_challenge=challenge
    )
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("/oidc/callback", name="oidc_callback", response_class=RedirectResponse)
async def oidc_callback(
    request: Request,
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Finish an SSO login: consume the state (one shot), exchange the code
    with PKCE, verify the id_token, link/create the user, set the refresh cookie."""
    from synapse_saas.core.errors import AuthenticationError

    if error:
        raise AuthenticationError(f"Identity provider refused the login: {error}")
    if not code or not state:
        raise AuthenticationError("Missing code or state")
    raw = await _oidc_state.get(state)
    if raw is None:
        raise AuthenticationError("Unknown or expired login state")
    await _oidc_state.delete(state)  # single use
    pending = json.loads(raw)

    provider = get_identity_provider()
    _, claims = await provider.exchange_oidc_code(
        code, redirect_uri=_callback_uri(request), code_verifier=pending["verifier"], nonce=pending["nonce"]
    )
    service = IdentityService(session)
    user = await service.link_or_create_oidc_user(claims)
    tokens = await service.issue_tokens(
        user,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    settings = get_settings()
    target = (
        f"{settings.web_origin.rstrip('/')}/auth/callback?return_to={quote(pending['return_to'], safe='/')}"
    )
    response = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
    _set_refresh_cookie(response, tokens.refresh_token)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: SessionDep) -> None:
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        await IdentityService(session).logout(token)
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserWithOrgs)
async def me(user: CurrentUser, session: SessionDep) -> UserWithOrgs:
    memberships = await MembershipRepository(session).for_user(user.id)
    orgs = [
        {
            "id": m.organization_id,
            "slug": m.organization.slug,
            "name": m.organization.name,
            "role_keys": sorted(r.key for r in m.roles),
        }
        for m in memberships
    ]
    read = UserWithOrgs.model_validate(user)
    read.orgs = orgs  # type: ignore[assignment]
    return read


@router.post("/switch-org", response_model=AccessTokenResponse)
async def switch_org(
    body: SwitchOrgRequest, user: CurrentUser, session: SessionDep, response: Response
) -> AccessTokenResponse:
    """Mint an org-scoped access token now (the `org` claim drives tenant resolution
    when no header is sent); the rotated refresh token goes into the cookie."""
    membership = await MembershipRepository(session).get_active(body.organization_id, user.id)
    if membership is None:
        from synapse_saas.core.errors import TenantNotResolvedError

        raise TenantNotResolvedError("Organization not found")

    service = IdentityService(session)
    tokens = await service.issue_tokens(user, organization_id=body.organization_id)
    _set_refresh_cookie(response, tokens.refresh_token)
    return AccessTokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/accept-invite", status_code=status.HTTP_200_OK)
async def accept_invite(body: InviteAcceptRequest, user: CurrentUser, session: SessionDep) -> dict[str, str]:
    """Accept an organization invitation with its emailed token (single-use)."""
    from synapse_saas.tenancy.service import OrganizationService

    membership = await OrganizationService(session).accept_invite_by_token(body.token, user)
    return {
        "organization_id": str(membership.organization_id),
        "status": membership.status,
    }


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(body: ForgotPasswordRequest, session: SessionDep) -> dict[str, bool]:
    service = IdentityService(session)
    reset = await service.request_password_reset(str(body.email))
    # Response is identical whether or not the email exists (no enumeration).
    # The link rides the outbox: worker emails it when SMTP is configured,
    # logs it otherwise. The token never enters the HTTP response.
    if reset is not None:
        row, token = reset
        from synapse_saas.core.logging import get_logger
        from synapse_saas.core.outbox import append_outbox

        get_logger(__name__).info("password_reset_requested", user_id=str(row.user_id))
        append_outbox(
            session,
            event_type="user.password_reset_link",
            aggregate_type="user",
            aggregate_id=row.user_id,
            organization_id=None,
            payload={"email": str(body.email), "token": token},
        )
    return {"ok": True}


@router.post("/reset-password", response_model=AuthResponse)
async def reset_password(body: ResetPasswordRequest, response: Response, session: SessionDep) -> AuthResponse:
    service = IdentityService(session)
    user = await service.reset_password(token=body.token, new_password=body.password)
    tokens = await service.issue_tokens(user)
    _set_refresh_cookie(response, tokens.refresh_token)
    return AuthResponse(user=UserRead.model_validate(user), tokens=tokens)
