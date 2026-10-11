"""Database query instrumentation helpers."""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from core.logging.logger import get_logger, log_debug, log_warning

logger = get_logger(__name__)

T = TypeVar("T")


async def instrument_db_call[T](
    operation: str,
    func: Callable[..., Awaitable[T]],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Run a DB operation with structured logs."""

    start = time.perf_counter()
    log_debug(logger, "Database query started", operation=operation)
    try:
        result = await func(*args, **kwargs)
    except Exception as exc:
        duration = time.perf_counter() - start
        log_warning(
            logger,
            "Database query failed",
            operation=operation,
            duration_ms=f"{duration * 1000:.3f}",
            error_type=type(exc).__name__,
        )
        raise
    duration = time.perf_counter() - start
    log_debug(
        logger,
        "Database query completed",
        operation=operation,
        duration_ms=f"{duration * 1000:.3f}",
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
