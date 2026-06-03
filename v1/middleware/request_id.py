"""Request ID tracing middleware."""

from __future__ import annotations

from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.config.settings import settings
from v1.middleware.state import (
    CORRELATION_ID_STATE_KEY,
    REQUEST_ID_STATE_KEY,
    ensure_state,
)


class RequestIdMiddleware:
    """Attach a request ID to request.state and response headers."""

    def __init__(self, app: ASGIApp, header_name: str) -> None:
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get(self.header_name) or uuid4().hex
        correlation_header = settings.observability.correlation_header
        correlation_id = headers.get(correlation_header) or request_id
        state = ensure_state(scope)
        state[REQUEST_ID_STATE_KEY] = request_id
        state[CORRELATION_ID_STATE_KEY] = correlation_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers.setdefault(self.header_name, request_id)
                response_headers.setdefault(correlation_header, correlation_id)
            await send(message)

        await self.app(scope, receive, send_with_request_id)
