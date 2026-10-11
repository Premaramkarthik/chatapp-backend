"""Service-layer observability helpers."""

from __future__ import annotations

import functools
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from core.logging.logger import get_logger, log_debug, log_warning

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def observe_service(service_name: str) -> Callable[[F], F]:
    """Decorator: structured entry/exit logs for service methods."""

    def decorator(func: F) -> F:
        method_name = func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:

            start = time.perf_counter()
            log_debug(
                logger,
                "Service method execution started",
                service=service_name,
                method=method_name,
            )
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                duration = time.perf_counter() - start
                log_warning(
                    logger,
                    "Service method execution failed",
                    service=service_name,
                    method=method_name,
                    duration_ms=f"{duration * 1000:.3f}",
                    error_type=type(exc).__name__,
                )
                raise
            duration = time.perf_counter() - start
            log_debug(
                logger,
                "Service method execution completed",
                service=service_name,
                method=method_name,
                duration_ms=f"{duration * 1000:.3f}",
            )
            return result

        return async_wrapper  # type: ignore[return-value]

    return decorator


@asynccontextmanager
async def log_external_call(operation: str) -> AsyncIterator[None]:
    """Context manager for external HTTP calls with logging."""
    start = time.perf_counter()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        duration = time.perf_counter() - start
        log_debug(
            logger,
            "External call completed",
            operation=operation,
            status=status,
            duration_ms=f"{duration * 1000:.3f}",
        )
