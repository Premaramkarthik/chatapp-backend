"""JWT authentication middleware."""

from __future__ import annotations

from fastapi import HTTPException, status
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from v1.core.settings import settings
from v1.middleware.state import AUTH_SESSION_STATE_KEY, PRINCIPAL_STATE_KEY, ensure_state
from v1.services.auth.session_resolver import auth_session_resolver
from v1.utils.exception import AuthenticationError
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

        headers = Headers(scope=scope)
        authorization = headers.get("authorization")
        if authorization:
            await self._authenticate_bearer(authorization, scope, receive, send)
            return

        session_token = _cookie_value(headers.get("cookie"), settings.auth.cookie_name)
        if session_token:
            await self._authenticate_session_cookie(session_token, scope, receive, send)
            return

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def _authenticate_bearer(
        self,
        authorization: str,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
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

    async def _authenticate_session_cookie(
        self,
        session_token: str,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        try:
            principal, session = await auth_session_resolver.resolve(session_token)
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        state = ensure_state(scope)
        state[PRINCIPAL_STATE_KEY] = principal
        state[AUTH_SESSION_STATE_KEY] = session
        await self.app(scope, receive, send)

    def _requires_auth(self, path: str) -> bool:
        if not settings.middleware.auth_enabled:
            return False
        if path in self.public_paths:
            return False
        if self.public_prefixes and path.startswith(self.public_prefixes):
            return False
        return path.startswith(self.protected_prefixes)


def _cookie_value(cookie_header: str | None, name: str) -> str | None:
    if not cookie_header:
        return None
    for item in cookie_header.split(";"):
        key, _, value = item.strip().partition("=")
        if key == name:
            return value
    return None
