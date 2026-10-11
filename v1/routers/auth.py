"""Hosted authentication, local-first logout and signed credential events."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from core.config.settings import settings
from domains.auth import AuthService, AuthSession
from domains.auth.security import hash_secret
from domains.users.bootstrap import BootstrapUser
from domains.users.user import BootstrapUserCommand
from infrastructure.keycloak.session_control import session_control
from v1.dependencies.auth import (
    get_current_auth_session,
    get_current_principal,
    get_revocation_session,
    require_capability,
)
from v1.dependencies.container import get_auth_service, get_bootstrap_user_use_case
from v1.schemas.auth_bff import (
    OnboardingCompleteRequest,
    RevokeAllSessionsRequest,
    SessionResponse,
    SigninStartRequest,
    SigninStartResponse,
)
from v1.schemas.principal import KeycloakPrincipal
from v1.schemas.users import UserResponse
from v1.utils.base import AuthenticationError, SigninCallbackError
from v1.utils.request_context import request_id_from
from v1.utils.user_session import build_user_response

router = APIRouter(prefix="/v1/auth", tags=["auth"])
AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
BootstrapUserUseCase = Annotated[BootstrapUser, Depends(get_bootstrap_user_use_case)]
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
CurrentSession = Annotated[AuthSession, Depends(get_current_auth_session)]
RevocationSession = Annotated[AuthSession, Depends(get_revocation_session)]
SessionManager = Annotated[KeycloakPrincipal, Depends(require_capability("session:manage"))]


@router.post("/signin/start", response_model=SigninStartResponse)
async def signin_start(
    payload: SigninStartRequest, request: Request, auth_service: AuthServiceDependency
):
    return await auth_service.start_signin(
        post_signin_redirect_uri=payload.post_signin_redirect_uri,
        identity_provider=payload.identity_provider,
        intent=payload.intent,
        request=request,
    )


async def retired_flow():
    raise HTTPException(
        410, detail={"code": "auth_flow_retired", "message": "Use Keycloak-hosted authentication"}
    )


for path in (
    "/signin/password",
    "/signup",
    "/signup/start",
    "/signup/complete",
    "/signup/resend",
    "/signup/verify/complete",
    "/signup/social/start",
    "/forgot-password",
    "/reset-password/complete",
):
    router.add_api_route(path, retired_flow, methods=["POST"], status_code=410)
router.add_api_route("/signup/verify/complete", retired_flow, methods=["GET"], status_code=410)


@router.get("/signin/callback")
async def signin_callback(
    request: Request,
    auth_service: AuthServiceDependency,
    code: str | None = Query(None),
    state: str = Query(...),
    error: str | None = Query(None),
):
    if error or not code:
        # Consume cancelled state so cancellation cannot become an open redirect or replay.
        await auth_service._auth_repository.consume_signin_state(state_hash=hash_secret(state))
        return RedirectResponse(
            settings.auth.default_post_signin_redirect_url + "?auth_error=signin_cancelled",
            status_code=303,
        )
    redirect = settings.auth.default_post_signin_redirect_url
    try:
        result = await auth_service.handle_callback(code=code, state=state, request=request)
        response = RedirectResponse(result.post_signin_redirect_uri, status_code=303)
        _set_auth_cookies(
            response, result.session_token, result.csrf_token, max_age=result.cookie_max_age_sec
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    except AuthenticationError as exc:
        if isinstance(exc, SigninCallbackError):
            redirect = exc.post_signin_redirect_uri
        sep = "&" if "?" in redirect else "?"
        return RedirectResponse(
            redirect + sep + urlencode({"auth_error": exc.code}), status_code=303
        )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: RevocationSession,
    auth_service: AuthServiceDependency,
):
    result = await auth_service.logout(session=session, request=request)
    _clear_auth_cookies(response)
    response.status_code = 200 if result["remote_termination"] == "complete" else 202
    try:
        result["browser_logout_url"] = await session_control.browser_logout_url()
    except HTTPException:
        result["browser_logout_url"] = None
    return result


@router.delete("/sessions/all")
async def revoke_all_sessions(
    payload: RevokeAllSessionsRequest,
    response: Response,
    request: Request,
    session: RevocationSession,
    auth_service: AuthServiceDependency,
):
    result = await auth_service.revoke_all_sessions(
        user_id=session.user_id,
        keycloak_sub=session.keycloak_sub,
        keep_session_id=session.id if payload.keep_current else None,
        request=request,
    )
    response.status_code = 200 if result["remote_termination"] == "complete" else 202
    if not payload.keep_current:
        _clear_auth_cookies(response)
    return result


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    request: Request,
    response: Response,
    session: RevocationSession,
    auth_service: AuthServiceDependency,
):
    result = await auth_service.revoke_session(
        session_id=session_id, user_id=session.user_id, request=request
    )
    response.status_code = 200 if result["remote_termination"] == "complete" else 202
    if session_id == session.id:
        _clear_auth_cookies(response)
    return result


@router.get("/session", response_model=UserResponse)
async def auth_session(
    request: Request,
    principal: CurrentPrincipal,
    bootstrap_user: BootstrapUserUseCase,
) -> dict:
    """Return the logged-in user for the current session cookie."""
    display_name = principal.display_name or principal.preferred_username
    user = await bootstrap_user.execute(
        BootstrapUserCommand(
            keycloak_sub=principal.sub,
            email=principal.email,
            display_name=display_name,
        ),
        request_id=request_id_from(request),
    )
    return await build_user_response(user)


@router.post("/onboarding/complete", response_model=UserResponse)
async def onboarding_complete(
    payload: OnboardingCompleteRequest,
    request: Request,
    principal: CurrentPrincipal,
    auth_service: AuthServiceDependency,
) -> dict:
    """Complete onboarding profile and role selection."""
    user = await auth_service.complete_onboarding(
        keycloak_sub=principal.sub,
        display_name=payload.display_name,
        account_mode=payload.account_mode,
        request=request,
    )
    return await build_user_response(user)


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    request: Request,
    _: SessionManager,
    session: CurrentSession,
    auth_service: AuthServiceDependency,
) -> list[SessionResponse]:
    """List the current user's active sessions."""
    sessions = await auth_service.list_sessions(user_id=session.user_id, request=request)
    return [
        SessionResponse(
            id=item.id,
            status=item.status.value,
            device_label=item.device_label,
            last_seen_at=item.last_seen_at,
            created_at=item.created_at,
            is_current=item.id == session.id,
        )
        for item in sessions
    ]


def _set_auth_cookies(
    response: Response,
    session_token: str,
    csrf_token: str,
    *,
    max_age: int | None,
) -> None:
    response.set_cookie(
        settings.auth.cookie_name,
        session_token,
        max_age=max_age,
        secure=settings.auth.cookie_secure,
        httponly=True,
        samesite=settings.auth.cookie_samesite,
        domain=settings.auth.cookie_domain_value,
    )
    response.set_cookie(
        settings.auth.csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        secure=settings.auth.cookie_secure,
        httponly=False,
        samesite=settings.auth.cookie_samesite,
        domain=settings.auth.cookie_domain_value,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        settings.auth.cookie_name,
        domain=settings.auth.cookie_domain_value,
    )
    response.delete_cookie(
        settings.auth.csrf_cookie_name,
        domain=settings.auth.cookie_domain_value,
    )
