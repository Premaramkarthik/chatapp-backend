"""Structured request/response logging middleware."""

from __future__ import annotations

import time
from typing import Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.logging.logger import get_logger
from core.observability.metrics import metrics_registry
from v1.middleware.state import (
    REQUEST_ID_STATE_KEY,
    START_TIME_STATE_KEY,
    ensure_state,
    state_value,
)

logger = get_logger(__name__)


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
        status_code: int | None = None
        error_type: str | None = None

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            duration_seconds = time.perf_counter() - start_time
            duration_ms = duration_seconds * 1000
            resolved_status_code = status_code or 500
            metrics_registry.record_http_request(
                method=scope["method"],
                path=scope["path"],
                status_code=resolved_status_code,
                duration_seconds=duration_seconds,
            )
            headers = Headers(scope=scope)
            client = scope.get("client")
            client_host = client[0] if client else None
            log_payload: dict[str, Any] = {
                "event": "http_request",
                "request_id": state_value(scope, REQUEST_ID_STATE_KEY),
                "method": scope["method"],
                "path": scope["path"],
                "status_code": resolved_status_code,
                "duration_ms": round(duration_ms, 3),
                "client_host": client_host,
                "user_agent": headers.get("user-agent"),
            }
            if error_type:
                log_payload["error_type"] = error_type
            logger.info("{}", log_payload)
