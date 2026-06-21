"""Matrix rate limiting via Redis."""

from __future__ import annotations

from core.config.settings import settings
from infrastructure.redis.cache import auth_redis_cache


class MatrixRateLimiter:
    """Per-user rate limits for chat operations."""

    async def check_message_limit(self, user_id: str) -> bool:
        count = await auth_redis_cache.increment(
            f"matrix:rate:message:{user_id}",
            ttl_sec=settings.matrix.message_rate_window_sec,
        )
        return count <= settings.matrix.message_rate_limit

    async def check_media_limit(self, user_id: str) -> bool:
        count = await auth_redis_cache.increment(
            f"matrix:rate:media:{user_id}",
            ttl_sec=settings.matrix.media_rate_window_sec,
        )
        return count <= settings.matrix.media_rate_limit


matrix_rate_limiter = MatrixRateLimiter()
