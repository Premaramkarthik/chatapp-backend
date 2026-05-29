"""Middleware behavior tests."""

import pytest

from infrastructure.redis.cache import InMemoryRedisFallback
from v1.middleware.rate_limit import InMemoryRateLimitStore


@pytest.mark.asyncio
async def test_in_memory_rate_limit_store_blocks_after_limit() -> None:
    store = InMemoryRateLimitStore()

    first = await store.hit("client:/path", limit=1, window_sec=60)
    second = await store.hit("client:/path", limit=1, window_sec=60)

    assert first.allowed is True
    assert first.remaining == 0
    assert second.allowed is False
    assert second.retry_after_sec > 0


@pytest.mark.asyncio
async def test_in_memory_redis_fallback_supports_nx_and_increment() -> None:
    cache = InMemoryRedisFallback()

    assert await cache.set("lock", "1", ex=60, nx=True) is True
    assert await cache.set("lock", "2", ex=60, nx=True) is False
    assert await cache.get("lock") == "1"
    assert await cache.incr("counter") == 1
    assert await cache.incr("counter") == 2
