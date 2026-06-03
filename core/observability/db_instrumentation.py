"""Database query instrumentation helpers."""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from core.logging.logger import get_logger
from core.observability.prometheus_metrics import (
    DATABASE_CONNECTIONS_ACTIVE,
    DATABASE_CONNECTIONS_IDLE,
    DATABASE_QUERY_DURATION_SECONDS,
    DATABASE_QUERY_FAILURES_TOTAL,
)

logger = get_logger(__name__)

T = TypeVar("T")


def update_pool_gauges(pool: Any) -> None:
    """Refresh asyncpg pool connection gauges."""
    try:
        size = pool.get_size()
        idle = pool.get_idle_size()
        DATABASE_CONNECTIONS_ACTIVE.set(max(0, size - idle))
        DATABASE_CONNECTIONS_IDLE.set(idle)
    except Exception:
        pass


async def instrument_db_call[T](
    operation: str,
    func: Callable[..., Awaitable[T]],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Run a DB operation with span, metrics, and structured logs."""
    from opentelemetry import trace

    tracer = trace.get_tracer(__name__)
    start = time.perf_counter()
    with tracer.start_as_current_span(
        "db.query",
        attributes={"db.system": "postgresql", "db.operation": operation},
    ):
        logger.debug("db_query_started operation={}", operation)
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            duration = time.perf_counter() - start
            DATABASE_QUERY_DURATION_SECONDS.labels(operation=operation).observe(duration)
            DATABASE_QUERY_FAILURES_TOTAL.labels(operation=operation).inc()
            logger.warning(
                "db_query_failed operation={} duration_ms={:.3f} error_type={}",
                operation,
                duration * 1000,
                type(exc).__name__,
            )
            raise
        duration = time.perf_counter() - start
        DATABASE_QUERY_DURATION_SECONDS.labels(operation=operation).observe(duration)
        logger.debug(
            "db_query_completed operation={} duration_ms={:.3f}",
            operation,
            duration * 1000,
        )
        return result


def db_operation(
    operation: str,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator for async DB helper functions."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await instrument_db_call(operation, func, *args, **kwargs)

        return wrapper

    return decorator
