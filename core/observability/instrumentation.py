"""Service-layer observability helpers."""

from __future__ import annotations

import functools
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from core.logging.logger import get_logger
from core.observability.prometheus_metrics import (
    KEYCLOAK_FAILURES_TOTAL,
    KEYCLOAK_REQUEST_DURATION_SECONDS,
    KEYCLOAK_REQUESTS_TOTAL,
    SERVICE_EXECUTION_DURATION_SECONDS,
)

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def observe_service(service_name: str) -> Callable[[F], F]:
    """Decorator: span, histogram, and structured entry/exit logs for service methods."""

    def decorator(func: F) -> F:
        method_name = func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            from opentelemetry import trace

            tracer = trace.get_tracer(__name__)
            start = time.perf_counter()
            with tracer.start_as_current_span(f"{service_name}.{method_name}"):
                logger.debug(
                    "service_execution_started service={} method={}",
                    service_name,
                    method_name,
                )
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    duration = time.perf_counter() - start
                    SERVICE_EXECUTION_DURATION_SECONDS.labels(
                        service=service_name,
                        method=method_name,
                    ).observe(duration)
                    logger.warning(
                        "service_execution_failed service={} method={} "
                        "duration_ms={:.3f} error_type={}",
                        service_name,
                        method_name,
                        duration * 1000,
                        type(exc).__name__,
                    )
                    raise
                duration = time.perf_counter() - start
                SERVICE_EXECUTION_DURATION_SECONDS.labels(
                    service=service_name,
                    method=method_name,
                ).observe(duration)
                logger.debug(
                    "service_execution_completed service={} method={} duration_ms={:.3f}",
                    service_name,
                    method_name,
                    duration * 1000,
                )
                return result

        return async_wrapper  # type: ignore[return-value]

    return decorator


@asynccontextmanager
async def log_external_call(operation: str) -> AsyncIterator[None]:
    """Context manager for external HTTP calls with metrics and logging."""
    start = time.perf_counter()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        KEYCLOAK_FAILURES_TOTAL.labels(operation=operation).inc()
        raise
    finally:
        duration = time.perf_counter() - start
        KEYCLOAK_REQUEST_DURATION_SECONDS.labels(operation=operation).observe(duration)
        KEYCLOAK_REQUESTS_TOTAL.labels(operation=operation, status=status).inc()
        logger.debug(
            "external_call_completed operation={} status={} duration_ms={:.3f}",
            operation,
            status,
            duration * 1000,
        )
