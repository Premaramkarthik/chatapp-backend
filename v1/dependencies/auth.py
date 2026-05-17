"""HTTP authentication dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from v1.middleware.state import PRINCIPAL_STATE_KEY
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.keyclock_adapter import keycloak_verifier

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
