"""Structured logging context and loguru patcher for observability."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
keycloak_sub_var: ContextVar[str | None] = ContextVar("keycloak_sub", default=None)
endpoint_var: ContextVar[str | None] = ContextVar("endpoint", default=None)
method_var: ContextVar[str | None] = ContextVar("method", default=None)
status_code_var: ContextVar[int | None] = ContextVar("status_code", default=None)
latency_ms_var: ContextVar[float | None] = ContextVar("latency_ms", default=None)


def bind_request_context(
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
    user_id: str | None = None,
    keycloak_sub: str | None = None,
    endpoint: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    latency_ms: float | None = None,
) -> None:
    """Bind HTTP context fields for structured logging."""
    if request_id is not None:
        request_id_var.set(request_id)
    if correlation_id is not None:
        correlation_id_var.set(correlation_id)
    if user_id is not None:
        user_id_var.set(user_id)
    if keycloak_sub is not None:
        keycloak_sub_var.set(keycloak_sub)
    if endpoint is not None:
        endpoint_var.set(endpoint)
    if method is not None:
        method_var.set(method)
    if status_code is not None:
        status_code_var.set(status_code)
    if latency_ms is not None:
        latency_ms_var.set(latency_ms)


def clear_request_context() -> None:
    """Reset context vars after a request completes."""
    for var in (
        request_id_var,
        correlation_id_var,
        user_id_var,
        keycloak_sub_var,
        endpoint_var,
        method_var,
        status_code_var,
        latency_ms_var,
    ):
        var.set(None)


def _trace_context() -> dict[str, str | None]:
    """Read OpenTelemetry trace context when available."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx is None or not ctx.is_valid:
            return {"trace_id": None, "span_id": None}
        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
        }
    except Exception:
        return {"trace_id": None, "span_id": None}


def observability_log_patcher(record: dict[str, Any]) -> None:
    """Inject observability fields into every log record."""
    from core.config.settings import settings

    extra = record["extra"]
    if not extra.get("logger_name"):
        extra["logger_name"] = record["name"]
    trace_ctx = _trace_context()
    extra.setdefault("service_name", settings.observability.service_name)
    extra.setdefault("environment", settings.app.environment)
    extra.setdefault("request_id", request_id_var.get())
    extra.setdefault("correlation_id", correlation_id_var.get())
    extra.setdefault("trace_id", trace_ctx["trace_id"])
    extra.setdefault("span_id", trace_ctx["span_id"])
    extra.setdefault("user_id", user_id_var.get())
    extra.setdefault("keycloak_sub", keycloak_sub_var.get())
    extra.setdefault("endpoint", endpoint_var.get())
    extra.setdefault("method", method_var.get())
    extra.setdefault("status_code", status_code_var.get())
    extra.setdefault("latency_ms", latency_ms_var.get())
