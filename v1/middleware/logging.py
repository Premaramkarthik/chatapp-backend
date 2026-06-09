"""Structured request/response logging middleware."""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.observability.logging_context import (
    bind_request_context,
    clear_request_context,
)
from v1.middleware.state import (
    CORRELATION_ID_STATE_KEY,
    REQUEST_ID_STATE_KEY,
    START_TIME_STATE_KEY,
    ensure_state,
    state_value,
)


class RequestResponseLoggingMiddleware:
    """Emit structured access logs for every HTTP request."""

    def __init__(self, app: ASGIApp, *, log_request_body: bool = False) -> None:
        self.app = app
        self.log_request_body = log_request_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        ensure_state(scope)[START_TIME_STATE_KEY] = start_time
        request_id = state_value(scope, REQUEST_ID_STATE_KEY)
        correlation_id = state_value(scope, CORRELATION_ID_STATE_KEY, request_id)
        bind_request_context(
            request_id=request_id,
            correlation_id=correlation_id,
            endpoint=scope["path"],
            method=scope["method"],
        )
        status_code: int | None = None

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            duration_seconds = time.perf_counter() - start_time
            duration_ms = duration_seconds * 1000
            resolved_status_code = status_code or 500
            bind_request_context(status_code=resolved_status_code, latency_ms=round(duration_ms, 3))
            clear_request_context()
