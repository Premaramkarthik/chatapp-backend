"""API asyncpg pool sizing: env tuning and optional inference from PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

from core.config.settings import settings
from core.logging.logger import get_logger, log_info, log_warning

logger = get_logger(__name__)

# When inference is off or fails, cap max pool size at this value per API process.
_FALLBACK_MAX_POOL = 4

# In PgBouncer session mode, client sessions generally hold server connections.
# Avoid accidental stampedes by defaulting to a tiny per-process pool cap when
# DB_TARGET=pgbouncer unless an explicit DB_POOL_MAX is configured.
_PGBOUNCER_SESSION_SAFE_MAX_POOL = 1

# Same buffer as infer_api_pool_max_from_server when dividing usable backends by workers.
_USABLE_BACKENDS_BUFFER = 2

_PG_POOL_LIMITS_SQL = """
SELECT
  (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max_connections,
  (SELECT setting::int FROM pg_settings WHERE name = 'superuser_reserved_connections')
    AS superuser_reserved,
  (SELECT rolconnlimit FROM pg_roles WHERE rolname = current_user) AS role_connection_limit;
"""


@dataclass(frozen=True)
class PgPoolLimitSnapshot:
    """Postgres limits read once for pool sizing (``pg_settings`` + role ``CONNECTION LIMIT``)."""

    max_connections: int
    superuser_reserved: int
    role_connection_limit: int | None


def _parse_explicit_max() -> int | None:
    raw = settings.database.pool_max
    if raw is None:
        return None
    return int(raw)


@dataclass(frozen=True)
class ApiDbPoolTuning:
    """Loaded once at import from ``DB_POOL_*`` env vars."""

    min_size: int
    explicit_max_size: int | None
    auto_infer: bool
    auto_concurrent_requests: int
    auto_ceiling: int

    @staticmethod
    def from_env() -> ApiDbPoolTuning:
        return ApiDbPoolTuning(
            min_size=settings.database.pool_min,
            explicit_max_size=_parse_explicit_max(),
            auto_infer=settings.database.pool_auto,
            auto_concurrent_requests=settings.database.pool_auto_estimated_concurrency,
            auto_ceiling=settings.database.pool_auto_ceiling,
        )


pool_tuning: ApiDbPoolTuning = ApiDbPoolTuning.from_env()


async def fetch_pg_pool_limit_snapshot(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
) -> PgPoolLimitSnapshot:
    """Read ``max_connections``, reserved slots, and current role connection limit from Postgres."""
    conn = await asyncpg.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    )
    try:
        row = await conn.fetchrow(_PG_POOL_LIMITS_SQL)
        if row is None:
            raise RuntimeError("limits query returned no row")
        max_conn = int(row["max_connections"])
        reserved = int(row["superuser_reserved"])
        role_limit = row["role_connection_limit"]
        role_int: int | None = None if role_limit is None else int(role_limit)
        return PgPoolLimitSnapshot(
            max_connections=max_conn,
            superuser_reserved=reserved,
            role_connection_limit=role_int,
        )
    finally:
        await conn.close()


def usable_backends_global(
    snapshot: PgPoolLimitSnapshot, *, buffer: int = _USABLE_BACKENDS_BUFFER
) -> int:
    """Approximate non-reserved backends available for the cluster (ignores other roles)."""
    return max(1, snapshot.max_connections - snapshot.superuser_reserved - buffer)


def peak_concurrent_api_workers_hint(
    *,
    snapshot: PgPoolLimitSnapshot,
    per_job_max_size: int,
    buffer: int = _USABLE_BACKENDS_BUFFER,
) -> int:
    """
    Rough upper bound on concurrent API processes if each may open ``per_job_max_size``
    server connections and nothing else uses Postgres (optimistic; tune down for v1, etc.).
    """
    usable_g = usable_backends_global(snapshot, buffer=buffer)
    cap_g = usable_g // max(1, per_job_max_size)
    rl = snapshot.role_connection_limit
    if rl is not None and rl >= 0:
        cap_r = max(1, rl // max(1, per_job_max_size))
        return max(1, min(cap_g, cap_r))
    return max(1, cap_g)


async def infer_api_pool_max_from_server(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    tuning: ApiDbPoolTuning | None = None,
) -> int:
    """
    Derive a conservative per-process pool max from PostgreSQL settings.

    Requires one temporary connection to read ``pg_settings`` and the current role's
    ``CONNECTION LIMIT``. Divide by ``tuning.auto_concurrent_requests``.
    """
    t = tuning or pool_tuning
    snap = await fetch_pg_pool_limit_snapshot(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    )
    usable_global = usable_backends_global(snap)
    jobs = max(1, t.auto_concurrent_requests)
    per_job_global = max(1, usable_global // jobs)

    rl = snap.role_connection_limit
    if rl is not None and rl >= 0:
        per_job_role = max(1, rl // jobs)
        per_job = min(per_job_global, per_job_role)
    else:
        per_job = per_job_global

    capped = min(t.auto_ceiling, per_job)
    return max(1, capped)


async def resolve_api_db_pool_min_max(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    tuning: ApiDbPoolTuning | None = None,
) -> tuple[int, int]:
    """Return ``(min_size, max_size)`` for this API process's asyncpg pool."""
    t = tuning or pool_tuning
    min_size = max(1, t.min_size)

    if t.explicit_max_size is not None:
        max_size = max(min_size, t.explicit_max_size)
        return min_size, max_size

    if settings.database.target_label == "pgbouncer" and t.auto_infer:
        max_size = max(min_size, _PGBOUNCER_SESSION_SAFE_MAX_POOL)
        log_warning(
            logger,
            "Using safe default pool size for PgBouncer session mode; set DB_POOL_MAX to override",
            max_size=max_size,
        )
        return min_size, max_size

    if not t.auto_infer:
        return min_size, max(min_size, _FALLBACK_MAX_POOL)

    try:
        inferred_max = await infer_api_pool_max_from_server(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            tuning=t,
        )
        max_size = max(min_size, inferred_max)
        log_info(
            logger,
            "Inferred API database pool max size from PostgreSQL settings",
            max_size=max_size,
            auto_concurrent_requests=t.auto_concurrent_requests,
        )
        return min_size, max_size
    except Exception as e:
        log_warning(
            logger,
            "Could not infer database pool size from server; using fallback max size",
            error=str(e),
            max_size=_FALLBACK_MAX_POOL,
        )
        return min_size, max(min_size, _FALLBACK_MAX_POOL)
