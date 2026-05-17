"""Middleware behavior tests."""

import pytest

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
