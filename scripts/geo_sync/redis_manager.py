"""Redis geo cache flush after successful sync."""

from __future__ import annotations

from infrastructure.redis.cache import geo_redis_cache


async def flush_geo_cache() -> int:
    """Flush all geo:* keys; returns number of keys deleted."""
    return await geo_redis_cache.flush_all()
