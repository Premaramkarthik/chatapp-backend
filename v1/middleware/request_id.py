"""Request ID tracing middleware."""

from __future__ import annotations

from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from v1.middleware.state import REQUEST_ID_STATE_KEY, ensure_state


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
        ensure_state(scope)[REQUEST_ID_STATE_KEY] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers.setdefault(self.header_name, request_id)
            await send(message)

        await self.app(scope, receive, send_with_request_id)
