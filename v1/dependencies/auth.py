"""HTTP authentication dependencies."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from domains.auth.models import AuthSession
from infrastructure.keycloak.adapter import keycloak_verifier
from v1.middleware.state import AUTH_SESSION_STATE_KEY, PRINCIPAL_STATE_KEY
from v1.schemas.principal import KeycloakPrincipal

bearer_scheme = HTTPBearer(auto_error=False)
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)]


async def get_revocation_session(request: Request) -> AuthSession:
    """Prove session ownership and its bound CSRF secret without remote authorization."""
    from core.config.settings import settings
    from domains.auth.security import hash_secret
    from domains.auth.session_resolver import auth_session_resolver
    from v1.utils.base import AuthenticationError

    token = request.cookies.get(settings.auth.cookie_name)
    if not token:
        raise HTTPException(401, detail="Session cookie authentication is required")
    try:
        session = await auth_session_resolver.resolve_for_revocation(token)
    except AuthenticationError as exc:
        raise HTTPException(401, detail={"code": exc.code}) from exc
    except Exception as exc:
        raise HTTPException(503, detail={"code": "local_revocation_failed"}) from exc
    csrf = request.headers.get(settings.auth.csrf_header_name, "")
    if not session.csrf_token_hash or not hmac.compare_digest(
        hash_secret(csrf), session.csrf_token_hash
    ):
        raise HTTPException(403, detail="Invalid CSRF token")
    return session


async def get_current_principal(
    request: Request,
    credentials: BearerCredentials,
) -> KeycloakPrincipal:
    """Return the authenticated principal for protected HTTP endpoints."""
    principal = getattr(request.state, PRINCIPAL_STATE_KEY, None)
    if isinstance(principal, KeycloakPrincipal):
        return principal

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = await keycloak_verifier.verify_token(credentials.credentials)
    from infrastructure.database.repositories.users import PostgresUserRepository
    from infrastructure.keycloak.session_control import session_control

    await session_control.check(principal)
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None or user.status not in {"active", "pending_profile_setup"}:
        raise HTTPException(401, detail="Account is disabled or not provisioned")
    return principal


async def get_current_auth_session(request: Request) -> AuthSession:
    """Return the current BFF auth session from request state."""
    session = getattr(request.state, AUTH_SESSION_STATE_KEY, None)
    if isinstance(session, AuthSession):
        return session
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session cookie authentication is required",
    )


def require_capability(capability: str) -> Callable:
    """Build a FastAPI dependency requiring a client/API capability role."""

    async def dependency(
        principal: Annotated[KeycloakPrincipal, Depends(get_current_principal)],
    ) -> KeycloakPrincipal:
        if capability in principal.roles or "admin" in principal.roles:
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required capability: {capability}",
        )

    return dependency


def require_any_capability(*capabilities: str) -> Callable:
    """Build a FastAPI dependency requiring at least one client/API capability role."""

    async def dependency(
        principal: Annotated[KeycloakPrincipal, Depends(get_current_principal)],
    ) -> KeycloakPrincipal:
        if "admin" in principal.roles or any(
            capability in principal.roles for capability in capabilities
        ):
            return principal
        missing = ", ".join(capabilities)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required capability (one of): {missing}",
        )

    return dependency
