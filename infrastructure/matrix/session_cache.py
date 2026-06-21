"""Redis cache for Matrix client access tokens."""

from __future__ import annotations

from typing import Any

from core.config.settings import settings
from infrastructure.redis.cache import auth_redis_cache


def matrix_session_cache_key(user_id: str) -> str:
    """Build the Redis key for a cached Matrix session snapshot."""
    return f"matrix:session:{user_id}"


async def get_cached_matrix_session(user_id: str) -> dict[str, Any] | None:
    """Return a cached Matrix session snapshot when present."""
    return await auth_redis_cache.get_json(matrix_session_cache_key(user_id))


async def cache_matrix_session(
    user_id: str,
    *,
    access_token: str,
    device_id: str | None,
    mxid: str,
    expires_in: int,
) -> None:
    """Cache Matrix login credentials for short-lived reuse."""
    ttl = min(expires_in, settings.matrix.session_cache_ttl_sec)
    if ttl <= 0:
        return
    await auth_redis_cache.set_json(
        matrix_session_cache_key(user_id),
        {
            "access_token": access_token,
            "device_id": device_id,
            "mxid": mxid,
            "expires_in": expires_in,
        },
        ttl_sec=ttl,
    )


async def invalidate_matrix_session(user_id: str) -> None:
    """Drop cached Matrix credentials for a user."""
    await auth_redis_cache.delete(matrix_session_cache_key(user_id))
