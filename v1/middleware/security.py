"""Security hardening middleware."""

from __future__ import annotations

from fastapi import HTTPException, status
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.config.settings import settings

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class SecurityHeadersMiddleware:
    """Attach common browser security headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        csp = _content_security_policy_for(scope)

        async def send_with_headers(message: Message) -> None:
            if scope["type"] == "http" and message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"content-security-policy", csp.encode()),
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class CSRFMiddleware:
    """Double-submit CSRF protection for cookie-authenticated unsafe requests."""

    def __init__(self, app: ASGIApp, *, excluded_paths: set[str]) -> None:
        self.app = app
        self.excluded_paths = excluded_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._requires_csrf(scope):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        session_cookie = _cookie_value(headers.get("cookie"), settings.auth.cookie_name)
        if not session_cookie:
            await self.app(scope, receive, send)
            return

        csrf_cookie = _cookie_value(headers.get("cookie"), settings.auth.csrf_cookie_name)
        csrf_header = headers.get(settings.auth.csrf_header_name)
        if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid CSRF token",
            )

        await self.app(scope, receive, send)

    def _requires_csrf(self, scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and settings.middleware.csrf_enabled
            and scope.get("method") in UNSAFE_METHODS
            and scope.get("path") not in self.excluded_paths
        )


def _cookie_value(cookie_header: str | None, name: str) -> str | None:
    if not cookie_header:
        return None
    for item in cookie_header.split(";"):
        key, _, value = item.strip().partition("=")
        if key == name:
            return value
    return None


def _content_security_policy_for(scope: Scope) -> str:
    if scope["type"] == "http" and scope.get("path") in settings.middleware.docs_csp_paths:
        return settings.middleware.docs_content_security_policy
    return settings.middleware.content_security_policy
