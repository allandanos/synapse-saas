"""Auth endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from synapse_saas.core.config import get_settings
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.identity.schemas import (
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


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
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


@router.post("/switch-org", status_code=status.HTTP_204_NO_CONTENT)
async def switch_org(
    body: SwitchOrgRequest, user: CurrentUser, session: SessionDep, response: Response
) -> None:
    """Record the active org; the next refresh mints an org-scoped token pair."""
    membership = await MembershipRepository(session).get_active(body.organization_id, user.id)
    if membership is None:
        from synapse_saas.core.errors import TenantNotResolvedError

        raise TenantNotResolvedError("Organization not found")

    # Mint a fresh pair immediately scoped to the org
    service = IdentityService(session)
    tokens = await service.issue_tokens(user, organization_id=body.organization_id)
    response.status_code = 200
    _set_refresh_cookie(response, tokens.refresh_token)
    from fastapi.responses import JSONResponse

    return JSONResponse(  # type: ignore[return-value]
        content={"access_token": tokens.access_token, "token_type": "bearer", "expires_in": tokens.expires_in}
    )


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
