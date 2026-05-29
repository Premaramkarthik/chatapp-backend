"""HTTP authentication dependencies."""

from __future__ import annotations

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
    return await keycloak_verifier.verify_token(credentials.credentials)


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
