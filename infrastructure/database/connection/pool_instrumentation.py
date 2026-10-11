from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from core.config.settings import settings
from core.logging.logger import get_logger, log_debug, log_warning

if TYPE_CHECKING:
    import asyncpg

logger = get_logger(__name__)

POOL_SERVICE = "api"


def db_target_label() -> str:
    """Return ``direct``, ``pgbouncer``, or ``unset`` from optional ``DB_TARGET`` env."""
    raw = settings.database.target_label
    if raw in ("direct", "pgbouncer"):
        return raw
    return "unset"


def log_pool_acquire_wait(service: str, wait_sec: float) -> None:
    """Emit structured acquire-wait line; warning when wait exceeds ``ACQUIRE_WARN_SEC``."""
    context = {
        "service": service,
        "db_target": db_target_label(),
        "wait_sec": f"{wait_sec:.6f}",
    }
    if wait_sec >= settings.database.pool_acquire_warn_sec:
        log_warning(logger, "Database pool acquire wait exceeded threshold", **context)
    else:
        log_debug(logger, "Database pool connection acquired", **context)


def log_pool_close(
    service: str, close_sec: float, *, ok: bool, error_type: str | None = None
) -> None:
    """Emit structured close timing; warning when close is slow or fails."""
    context: dict[str, str | bool] = {
        "service": service,
        "db_target": db_target_label(),
        "ok": ok,
        "close_sec": f"{close_sec:.6f}",
    }
    if error_type:
        context["error_type"] = error_type

    if (not ok) or close_sec >= settings.database.pool_close_warn_sec:
        log_warning(logger, "Database pool close completed slowly or with failure", **context)
    else:
        log_debug(logger, "Database pool closed", **context)


async def close_pool_with_instrumentation(pool: asyncpg.Pool, service: str = POOL_SERVICE) -> None:
    """Close an asyncpg pool and emit a structured timing line."""
    time.perf_counter()
    try:
        await pool.close()
    except Exception:
        pass
        raise
    else:
        pass


class InstrumentedAsyncpgPool:
    """
    Wraps an asyncpg pool so ``acquire()`` records wait time before the connection is usable.

    Only ``get_pool()`` returns this type; ``DatabasePool`` stores the raw asyncpg pool.
    """

    __slots__ = ("_pool",)

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @property
    def raw_pool(self) -> asyncpg.Pool:
        """Underlying asyncpg pool (for tests and rare direct access)."""
        return self._pool

    def acquire(self, *, timeout: float | None = None) -> _AcquireWaitLoggingContext:
        return _AcquireWaitLoggingContext(self._pool, POOL_SERVICE, timeout)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pool, name)


class _AcquireWaitLoggingContext:
    __slots__ = ("_holder", "_service")

    def __init__(
        self,
        pool: asyncpg.Pool,
        service: str,
        timeout: float | None,
    ) -> None:
        self._holder = pool.acquire(timeout=timeout)
        self._service = service

    async def __aenter__(self) -> asyncpg.Connection:
        t0 = time.perf_counter()
        conn = await self._holder.__aenter__()
        wait_sec = time.perf_counter() - t0
        log_pool_acquire_wait(self._service, wait_sec)
        return conn

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        return await self._holder.__aexit__(exc_type, exc, tb)


def wrap_pool_for_acquire_instrumentation(
    pool: asyncpg.Pool,
) -> InstrumentedAsyncpgPool:
    """Return a pool whose ``acquire()`` emits acquire-wait logs."""
    if isinstance(pool, InstrumentedAsyncpgPool):
        return pool
    return InstrumentedAsyncpgPool(pool)
