import asyncio
import threading
import weakref
from collections.abc import AsyncGenerator
from typing import Any, cast

import asyncpg

from core.config.settings import settings
from core.logging.logger import get_logger, log_error, log_exception, log_info, log_warning
from core.observability.db_instrumentation import db_operation
from infrastructure.database.connection.pool_instrumentation import (
    close_pool_with_instrumentation,
    db_target_label,
    wrap_pool_for_acquire_instrumentation,
)
from infrastructure.database.connection.pool_sizing import (
    resolve_api_db_pool_min_max,
)
from v1.utils.base import DatabaseConnectionError

logger = get_logger(__name__)

# One pool per running event loop.
_pools: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncpg.Pool] = (
    weakref.WeakKeyDictionary()
)
_pools_mutex = threading.Lock()
# Synchronous fallback used only in tests or rare sync contexts.
_sync_pool_ref: dict[str, asyncpg.Pool | None] = {"pool": None}

# Single-flight pool creation per event loop. A module-level asyncio.Lock is bound to one
# loop only, so we keep one Lock per loop.
_pool_init_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)
_pool_init_locks_mutex = threading.Lock()


def _pool_init_lock_for_running_loop() -> asyncio.Lock:
    """Return an ``asyncio.Lock`` bound to the currently running event loop."""
    loop = asyncio.get_running_loop()
    with _pool_init_locks_mutex:
        lock = _pool_init_locks.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            _pool_init_locks[loop] = lock
        return lock


async def _resolved_api_pool_min_max() -> tuple[int, int]:
    """Return ``(min_size, max_size)`` for this API process's asyncpg pool."""
    return await resolve_api_db_pool_min_max(
        host=settings.database.host,
        port=settings.database.port,
        user=settings.database.user,
        password=settings.database.password_value,
        database=settings.database.name,
    )


class DatabasePool:
    """Manages one asyncpg pool per running event loop."""

    def get_pool(self) -> asyncpg.Pool | None:
        """Get the database pool for the current event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return _sync_pool_ref["pool"]
        with _pools_mutex:
            return _pools.get(loop)

    @classmethod  # pyright: ignore[reportArgumentType]
    def set_pool(cls, pool: asyncpg.Pool | None) -> None:
        """Set the database pool for the current event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            _sync_pool_ref["pool"] = pool
            return
        with _pools_mutex:
            if pool is None:
                _pools.pop(loop, None)
            else:
                _pools[loop] = pool

    async def close(self) -> None:
        """Close the database pool for the current event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pool = _sync_pool_ref["pool"]
            _sync_pool_ref["pool"] = None
        else:
            with _pools_mutex:
                pool = _pools.pop(loop, None)

        if pool is None:
            return

        await close_pool_with_instrumentation(pool)
        log_info(logger, "Database connection pool closed for current context")


# Module-level accessor for backward compatibility
_db = DatabasePool()


async def get_db() -> AsyncGenerator[asyncpg.Connection]:
    """
    Async dependency function to get database connection from pool.
    """
    pool = await get_pool()
    async with pool.acquire() as connection:
        yield connection


async def init_db() -> asyncpg.Pool:
    """Initialize database connection pool for the current context."""
    return await connect_to_db_with_retry()


async def connect_to_db_with_retry(max_retries: int = 5, delay: float = 2.0) -> asyncpg.Pool:
    """
    Establish a connection pool with exponential backoff retries.

    Retries transient errors including ``TooManyConnectionsError`` when many job processes
    compete for Postgres ``max_connections``.
    """
    min_size, max_size = await _resolved_api_pool_min_max()
    app_host, app_port = settings.database.application_host_port
    log_info(
        logger,
        "Connecting to PostgreSQL for API database pool",
        service="api",
        db_target=db_target_label(),
        db_host=app_host,
        db_port=app_port,
        db_name=settings.database.name,
        db_user=settings.database.user,
        pool_min=min_size,
        pool_max=max_size,
    )

    retry_errors = (
        asyncpg.exceptions.InterfaceError,
        asyncpg.exceptions.CannotConnectNowError,
        asyncpg.exceptions.TooManyConnectionsError,
        OSError,
        TimeoutError,
    )
    fallback_errors = (
        asyncpg.exceptions.InterfaceError,
        asyncpg.exceptions.CannotConnectNowError,
        OSError,
        TimeoutError,
    )

    async def create_pool(host: str, port: int) -> asyncpg.Pool:
        last_error: BaseException | None = None
        for attempt in range(1, max_retries + 1):
            try:
                return await asyncpg.create_pool(
                    host=host,
                    port=port,
                    user=settings.database.user,
                    password=settings.database.password_value,
                    database=settings.database.name,
                    min_size=min_size,
                    max_size=max_size,
                    command_timeout=settings.database.command_timeout_sec,
                    timeout=settings.database.connect_timeout_sec,
                    init=_init_connection,
                )
            except (
                asyncpg.exceptions.InvalidPasswordError,
                asyncpg.exceptions.InvalidAuthorizationSpecificationError,
            ):
                raise
            except retry_errors as exc:
                last_error = exc
                log_warning(
                    logger,
                    "Database pool connection attempt failed; retrying",
                    service="api",
                    db_target=db_target_label(),
                    attempt=attempt,
                    max_retries=max_retries,
                    error_type=type(exc).__name__,
                )
                if attempt < max_retries:
                    await asyncio.sleep(delay * attempt)
        assert last_error is not None
        raise last_error

    fallback_used = False
    try:
        pool = await create_pool(app_host, app_port)
    except (
        asyncpg.exceptions.InvalidPasswordError,
        asyncpg.exceptions.InvalidAuthorizationSpecificationError,
    ) as e:
        error_msg = f"Database authentication failed for user '{settings.database.user}'."
        log_error(logger, error_msg)
        raise DatabaseConnectionError(error_msg) from e
    except retry_errors as pgbouncer_error:
        if settings.database.target_label != "pgbouncer":
            log_exception(logger, "Could not connect to PostgreSQL after retries")
            raise DatabaseConnectionError(
                "Could not connect to PostgreSQL after retries"
            ) from pgbouncer_error
        if not isinstance(pgbouncer_error, fallback_errors):
            raise DatabaseConnectionError(
                "Could not connect to PgBouncer after retries"
            ) from pgbouncer_error
        log_warning(
            logger,
            "PgBouncer is unavailable after retries; falling back to direct PostgreSQL",
            service="api",
            error_type=type(pgbouncer_error).__name__,
        )
        fallback_used = True
        try:
            pool = await create_pool(settings.database.host, settings.database.port)
        except (
            asyncpg.exceptions.InvalidPasswordError,
            asyncpg.exceptions.InvalidAuthorizationSpecificationError,
        ) as e:
            error_msg = f"Database authentication failed for user '{settings.database.user}'."
            log_error(logger, error_msg)
            raise DatabaseConnectionError(error_msg) from e
        except retry_errors as e:
            log_exception(logger, "Could not connect to PostgreSQL after retries")
            raise DatabaseConnectionError("Could not connect to PostgreSQL after retries") from e

    _db.set_pool(pool)
    connected_host, connected_port = (
        (settings.database.host, settings.database.port)
        if fallback_used
        else (app_host, app_port)
    )
    log_info(
        logger,
        "API database connection pool is ready",
        service="api",
        db_target=db_target_label(),
        pool_min=min_size,
        pool_max=max_size,
        db_host=connected_host,
        db_port=connected_port,
        db_name=settings.database.name,
        initial_pool_size=pool.get_size(),
    )
    return pool


async def close_db() -> None:
    """Close database connection pool in the current context."""
    await _db.close()


async def get_pool() -> asyncpg.Pool:
    """
    Returns the context-local database pool. Initializes if needed (single-flight per loop).
    """
    pool = _db.get_pool()
    if pool is not None:
        return cast("asyncpg.Pool", wrap_pool_for_acquire_instrumentation(pool))
    async with _pool_init_lock_for_running_loop():
        pool = _db.get_pool()
        if pool is not None:
            return cast("asyncpg.Pool", wrap_pool_for_acquire_instrumentation(pool))
        pool = await connect_to_db_with_retry()
        return cast("asyncpg.Pool", wrap_pool_for_acquire_instrumentation(pool))


async def _init_connection(connection: asyncpg.Connection) -> None:
    """Configure codecs for JSON/JSONB so stored functions can accept dict payloads."""
    for type_name in ("json", "jsonb"):
        await connection.set_type_codec(
            type_name,
            encoder=_json_encode,
            decoder=_json_decode,
            schema="pg_catalog",
            format="text",
        )


def _json_encode(value: Any) -> str:
    import json

    return json.dumps(value)


def _json_decode(value: str) -> Any:
    import json

    return json.loads(value)


async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    """Run a query and return one row."""
    return await _fetchrow(query, *args)


@db_operation("fetchrow")
async def _fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetchrow(query, *args)


async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    """Run a query and return all rows."""
    return await _fetch(query, *args)


@db_operation("fetch")
async def _fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    pool = await get_pool()
    async with pool.acquire() as connection:
        return list(await connection.fetch(query, *args))


async def execute(query: str, *args: Any) -> str:
    """Run a statement and return asyncpg's status text."""
    return await _execute(query, *args)


@db_operation("execute")
async def _execute(query: str, *args: Any) -> str:
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.execute(query, *args)


async def call_json_function(function_name: str, mode: int, payload: dict[str, Any]) -> Any:
    """Call a mode-based JSONB stored function."""
    return await _call_json_function(function_name, mode, payload)


@db_operation("call_json_function")
async def _call_json_function(function_name: str, mode: int, payload: dict[str, Any]) -> Any:
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            f"SELECT {function_name}($1, $2::jsonb) AS result",
            mode,
            payload,
        )
    if row is None:
        return None
    return row["result"]
