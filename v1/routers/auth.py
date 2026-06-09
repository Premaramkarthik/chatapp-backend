"""BFF authentication routes."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from core.config.settings import settings
from domains.auth import AuthService, AuthSession
from domains.users.bootstrap import BootstrapUser
from domains.users.user import BootstrapUserCommand
from v1.dependencies.auth import (
    get_current_auth_session,
    get_current_principal,
    require_capability,
)
from v1.dependencies.container import get_auth_service, get_bootstrap_user_use_case
from v1.schemas.auth_bff import (
    EmailVerificationCompleteRequest,
    EmailVerificationCompleteResponse,
    ForgotPasswordRequest,
    GenericAuthResponse,
    LogoutResponse,
    OnboardingCompleteRequest,
    ResetPasswordCompleteRequest,
    RevokeAllSessionsRequest,
    RevokeAllSessionsResponse,
    SessionResponse,
    SigninPasswordRequest,
    SigninPasswordResponse,
    SigninStartRequest,
    SigninStartResponse,
    SignupAcceptedResponse,
    SignupCompleteRequest,
    SignupCompleteResponse,
    SignupRequest,
    SignupResendRequest,
    SignupStartRequest,
    SignupStartResponse,
    SocialSignupStartRequest,
)
from v1.schemas.principal import KeycloakPrincipal
from v1.schemas.users import UserResponse
from v1.utils.base import AuthenticationError, SigninCallbackError
from v1.utils.request_context import request_id_from

router = APIRouter(prefix="/v1/auth", tags=["auth"])

AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
BootstrapUserUseCase = Annotated[BootstrapUser, Depends(get_bootstrap_user_use_case)]
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
        identity_provider=payload.identity_provider,
        account_mode=payload.account_mode,
        device_fingerprint=payload.device_fingerprint,
        captcha_token=payload.captcha_token,
        request=request,
    )
    return SigninStartResponse(
        authorization_url=result.authorization_url,
        state=result.state,
        expires_at=result.expires_at,
    )


@router.post("/signin/password", response_model=SigninPasswordResponse)
async def signin_password(
    payload: SigninPasswordRequest,
    request: Request,
    response: Response,
    auth_service: AuthServiceDependency,
) -> SigninPasswordResponse:
    """Sign in with email and password; sets BFF session cookies."""
    result = await auth_service.signin_password(
        email=str(payload.email),
        password=payload.password.get_secret_value(),
        remember_me=payload.remember_me,
        request=request,
    )
    _set_auth_cookies(
        response,
        result.session_token,
        result.csrf_token,
        max_age=result.cookie_max_age_sec,
    )
    return SigninPasswordResponse(user=UserResponse.model_validate(result.user.to_dict()))


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
    return user.to_dict()


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
    return user.to_dict()


@router.post("/signup/start", response_model=SignupStartResponse, status_code=202)
async def signup_start(
    payload: SignupStartRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> SignupStartResponse:
    """Create a pending account, set password in Keycloak, and send verify-only email."""
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    result = await auth_service.signup_start(
        email=str(payload.email),
        password=payload.password.get_secret_value(),
        device_fingerprint=payload.device_fingerprint,
        captcha_token=payload.captcha_token,
        idempotency_key=idempotency_key,
        request=request,
    )
    return SignupStartResponse(
        status=result.status,
        next_step=result.next_step,
        signup_token=result.signup_token,
        expires_at=result.expires_at,
    )


@router.post("/signup/complete", response_model=SignupCompleteResponse)
async def signup_complete(
    payload: SignupCompleteRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> SignupCompleteResponse:
    """Complete signup profile for a pending verification user."""
    result = await auth_service.signup_complete(
        signup_token=payload.signup_token,
        display_name=payload.display_name,
        account_mode=payload.account_mode,
        request=request,
    )
    return SignupCompleteResponse(status=result.status, next_step=result.next_step)


@router.post("/signup", status_code=410)
async def signup(
    _payload: SignupRequest,
    _request: Request,
) -> None:
    """Deprecated single-step signup; use /signup/start and /signup/complete."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "POST /v1/auth/signup is deprecated; "
            "use /v1/auth/signup/start and /v1/auth/signup/complete"
        ),
    )


@router.post("/signup/resend", response_model=SignupAcceptedResponse, status_code=202)
async def signup_resend(
    payload: SignupResendRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> SignupAcceptedResponse:
    """Resend account verification/setup email with abuse controls."""
    result = await auth_service.resend_signup_email(email=str(payload.email), request=request)
    return SignupAcceptedResponse(
        status=result.status,
        next_step=result.next_step,
        cooldown_sec=settings.auth.signup_resend_cooldown_sec,
    )


@router.post(
    "/signup/verify/complete",
    response_model=EmailVerificationCompleteResponse,
)
async def signup_verify_complete(
    payload: EmailVerificationCompleteRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> EmailVerificationCompleteResponse:
    """Consume an app-owned email verification token."""
    await auth_service.complete_email_verification(token=payload.token, request=request)
    return EmailVerificationCompleteResponse()


@router.get(
    "/signup/verify/complete",
    response_model=EmailVerificationCompleteResponse,
)
async def signup_verify_complete_get(
    request: Request,
    auth_service: AuthServiceDependency,
    token: str = Query(..., min_length=16, max_length=512),
) -> EmailVerificationCompleteResponse:
    """Consume an app-owned email verification token from a browser-safe GET."""
    await auth_service.complete_email_verification(token=token, request=request)
    return EmailVerificationCompleteResponse()


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
    redirect_uri = settings.auth.default_post_signin_redirect_url
    try:
        result = await auth_service.handle_callback(code=code, state=state, request=request)
        redirect_target = _redirect_with_user_payload(
            result.post_signin_redirect_uri,
            result.user.to_dict(),
        )
        response = RedirectResponse(redirect_target, status_code=303)
        _set_auth_cookies(
            response,
            result.session_token,
            result.csrf_token,
            max_age=result.cookie_max_age_sec,
        )
        return response
    except SigninCallbackError as exc:
        redirect_uri = exc.post_signin_redirect_uri
        query = urlencode({"auth_error": exc.code, "auth_message": exc.message})
        separator = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(f"{redirect_uri}{separator}{query}", status_code=303)
    except AuthenticationError as exc:
        query = urlencode({"auth_error": exc.code, "auth_message": exc.message})
        separator = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(f"{redirect_uri}{separator}{query}", status_code=303)


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
    """Send an app-owned password reset email with generic public response."""
    await auth_service.forgot_password(email=str(payload.email), request=request)
    return GenericAuthResponse()


@router.post("/reset-password/complete", response_model=GenericAuthResponse)
async def reset_password_complete(
    payload: ResetPasswordCompleteRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> GenericAuthResponse:
    """Complete app-owned password reset using a one-time token."""
    await auth_service.complete_password_reset(
        token=payload.token,
        password=payload.password.get_secret_value(),
        request=request,
    )
    return GenericAuthResponse()


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
        keycloak_sub=session.keycloak_sub,
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


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def _redirect_with_user_payload(redirect_uri: str, user: dict) -> str:
    """Append signed-in user JSON to the redirect URL hash for immediate client login."""
    payload = (
        base64.urlsafe_b64encode(
            json.dumps(user, default=_json_default, separators=(",", ":")).encode(),
        )
        .decode()
        .rstrip("=")
    )
    return f"{redirect_uri}#u={payload}"


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
