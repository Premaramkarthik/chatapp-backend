"""BFF authentication routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from v1.core.settings import settings
from v1.dependencies.auth import (
    get_current_auth_session,
    get_current_principal,
    require_capability,
)
from v1.dependencies.container import get_auth_service
from v1.schemas.auth_bff import (
    ForgotPasswordRequest,
    GenericAuthResponse,
    LogoutResponse,
    RevokeAllSessionsRequest,
    RevokeAllSessionsResponse,
    SessionResponse,
    SigninStartRequest,
    SigninStartResponse,
    SignupAcceptedResponse,
    SignupRequest,
    SignupResendRequest,
    SocialSignupStartRequest,
)
from v1.schemas.principal import KeycloakPrincipal
from v1.services.auth import AuthService, AuthSession

router = APIRouter(prefix="/v1/auth", tags=["auth"])

AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
CurrentSession = Annotated[AuthSession, Depends(get_current_auth_session)]
SessionManager = Annotated[KeycloakPrincipal, Depends(require_capability("session:manage"))]


@router.post("/signin/start", response_model=SigninStartResponse)
async def signin_start(
    payload: SigninStartRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> SigninStartResponse:
    """Begin Authorization Code + PKCE signin."""
    result = await auth_service.start_signin(
        post_signin_redirect_uri=payload.post_signin_redirect_uri,
        request=request,
    )
    return SigninStartResponse(
        authorization_url=result.authorization_url,
        state=result.state,
        expires_at=result.expires_at,
    )


@router.post("/signup", response_model=SignupAcceptedResponse, status_code=202)
async def signup(
    payload: SignupRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> SignupAcceptedResponse:
    """Create a pending account and send Keycloak setup email."""
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    result = await auth_service.signup(
        email=str(payload.email),
        display_name=payload.display_name,
        account_mode=payload.account_mode,
        device_fingerprint=payload.device_fingerprint,
        captcha_token=payload.captcha_token,
        idempotency_key=idempotency_key,
        request=request,
    )
    return SignupAcceptedResponse(status=result.status, next_step=result.next_step)


@router.post("/signup/resend", response_model=SignupAcceptedResponse, status_code=202)
async def signup_resend(
    payload: SignupResendRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> SignupAcceptedResponse:
    """Resend account verification/setup email with abuse controls."""
    result = await auth_service.resend_signup_email(email=str(payload.email), request=request)
    return SignupAcceptedResponse(status=result.status, next_step=result.next_step)


@router.post("/signup/social/start", response_model=SigninStartResponse)
async def social_signup_start(
    payload: SocialSignupStartRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> SigninStartResponse:
    """Begin Google/Apple signup with app account mode captured."""
    result = await auth_service.start_social_signup(
        identity_provider=payload.identity_provider,
        account_mode=payload.account_mode,
        device_fingerprint=payload.device_fingerprint,
        captcha_token=payload.captcha_token,
        post_signin_redirect_uri=payload.post_signin_redirect_uri,
        request=request,
    )
    return SigninStartResponse(
        authorization_url=result.authorization_url,
        state=result.state,
        expires_at=result.expires_at,
    )


@router.get("/signin/callback")
async def signin_callback(
    request: Request,
    auth_service: AuthServiceDependency,
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """Complete Keycloak signin callback and set BFF cookies."""
    result = await auth_service.handle_callback(code=code, state=state, request=request)
    response = RedirectResponse(result.post_signin_redirect_uri, status_code=303)
    _set_auth_cookies(response, result.session_token, result.csrf_token)
    return response


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    session: CurrentSession,
    auth_service: AuthServiceDependency,
) -> LogoutResponse:
    """Revoke current BFF session and clear cookies."""
    logout_url = await auth_service.logout(session=session, request=request)
    _clear_auth_cookies(response)
    return LogoutResponse(logout_url=logout_url)


@router.post("/forgot-password", response_model=GenericAuthResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> GenericAuthResponse:
    """Trigger a Keycloak password reset email with generic public response."""
    await auth_service.forgot_password(email=str(payload.email), request=request)
    return GenericAuthResponse()


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    _: SessionManager,
    principal: CurrentPrincipal,
    session: CurrentSession,
    auth_service: AuthServiceDependency,
) -> list[SessionResponse]:
    """List the current user's active sessions."""
    sessions = await auth_service.list_sessions(user_id=session.user_id)
    return [
        SessionResponse(
            id=item.id,
            status=item.status.value,
            device_label=item.device_label,
            last_seen_at=item.last_seen_at,
            created_at=item.created_at,
        )
        for item in sessions
    ]


@router.delete("/sessions/all", response_model=RevokeAllSessionsResponse)
async def revoke_all_sessions(
    payload: RevokeAllSessionsRequest,
    request: Request,
    _: SessionManager,
    session: CurrentSession,
    auth_service: AuthServiceDependency,
) -> RevokeAllSessionsResponse:
    """Revoke all sessions owned by the current user."""
    keep_session_id = session.id if payload.keep_current else None
    count = await auth_service.revoke_all_sessions(
        user_id=session.user_id,
        keep_session_id=keep_session_id,
        request=request,
    )
    return RevokeAllSessionsResponse(revoked_count=count)


@router.delete("/sessions/{session_id}", response_model=GenericAuthResponse)
async def revoke_session(
    session_id: str,
    request: Request,
    _: SessionManager,
    session: CurrentSession,
    auth_service: AuthServiceDependency,
) -> GenericAuthResponse:
    """Revoke one session owned by the current user."""
    await auth_service.revoke_session(
        session_id=session_id,
        user_id=session.user_id,
        request=request,
    )
    return GenericAuthResponse()


def _set_auth_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    response.set_cookie(
        settings.auth.cookie_name,
        session_token,
        max_age=settings.auth.session_max_sec,
        secure=settings.auth.cookie_secure,
        httponly=True,
        samesite=settings.auth.cookie_samesite,
        domain=settings.auth.cookie_domain_value,
    )
    response.set_cookie(
        settings.auth.csrf_cookie_name,
        csrf_token,
        max_age=settings.auth.session_max_sec,
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
