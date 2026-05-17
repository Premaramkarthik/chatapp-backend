"""JWT authentication middleware."""

from __future__ import annotations

from fastapi import HTTPException, status
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from v1.core.settings import settings
from v1.middleware.state import PRINCIPAL_STATE_KEY, ensure_state
from v1.utils.keyclock_adapter import keycloak_verifier


class JWTAuthenticationMiddleware:
    """Verify Keycloak JWTs for protected routes and attach principal to request.state."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        protected_prefixes: tuple[str, ...],
        public_paths: set[str],
        public_prefixes: tuple[str, ...],
    ) -> None:
        self.app = app
        self.protected_prefixes = protected_prefixes
        self.public_paths = public_paths
        self.public_prefixes = public_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._requires_auth(scope["path"]):
            await self.app(scope, receive, send)
            return

        authorization = Headers(scope=scope).get("authorization")
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        principal = await keycloak_verifier.verify_token(token)
        ensure_state(scope)[PRINCIPAL_STATE_KEY] = principal
        await self.app(scope, receive, send)

    def _requires_auth(self, path: str) -> bool:
        if not settings.middleware.auth_enabled:
            return False
        if path in self.public_paths:
            return False
        if self.public_prefixes and path.startswith(self.public_prefixes):
            return False
        return path.startswith(self.protected_prefixes)
