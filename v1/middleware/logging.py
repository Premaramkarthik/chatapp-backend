"""Structured request/response logging middleware."""

from __future__ import annotations

import time

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.logging.logger import get_logger
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
        request_id = state_value(scope, REQUEST_ID_STATE_KEY)
        correlation_id = state_value(scope, CORRELATION_ID_STATE_KEY, request_id)
        bind_request_context(
            request_id=request_id,
            correlation_id=correlation_id,
            endpoint=scope["path"],
            method=scope["method"],
        )
        status_code: int | None = None
        error_type: str | None = None
        response_size: int | None = None

        logger.info(
            "http_request_started method={} path={} request_id={}",
            scope["method"],
            scope["path"],
            request_id,
        )

        async def send_with_status(message: Message) -> None:
            nonlocal status_code, response_size
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    response_size = (response_size or 0) + len(body)
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
            bind_request_context(status_code=resolved_status_code, latency_ms=round(duration_ms, 3))
            headers = Headers(scope=scope)
            client = scope.get("client")
            client_host = client[0] if client else None
            duration_ms_rounded = round(duration_ms, 3)
            optional_fields = ""
            if response_size is not None:
                optional_fields += f" response_size={response_size}"
            if error_type:
                optional_fields += f" error_type={error_type}"
            message = (
                "http_request_completed method={} path={} status_code={} duration_ms={} "
                "request_id={} correlation_id={} client_host={} user_agent={}{}"
            )
            log_args = (
                scope["method"],
                scope["path"],
                resolved_status_code,
                duration_ms_rounded,
                request_id,
                correlation_id,
                client_host,
                headers.get("user-agent"),
                optional_fields,
            )
            if resolved_status_code >= 500:
                logger.error(message, *log_args)
            elif resolved_status_code >= 400:
                logger.warning(message, *log_args)
            else:
                logger.info(message, *log_args)
            clear_request_context()
