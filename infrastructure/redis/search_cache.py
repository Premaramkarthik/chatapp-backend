"""Search result cache with tiered TTLs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.config.settings import settings
from core.logging.logger import get_logger, log_warning
from infrastructure.redis.cache import AuthRedisCache, auth_redis_cache

logger = get_logger(__name__)


class SearchRedisCache:
    """Redis cache facade for Typesense search results."""

    def __init__(self, delegate: AuthRedisCache | None = None) -> None:
        self._delegate = delegate or auth_redis_cache

    @staticmethod
    def _hash_parts(**parts: Any) -> str:
        normalized = "|".join(f"{k}={v}" for k, v in sorted(parts.items()))
        return hashlib.sha256(normalized.encode()).hexdigest()[:24]

    def key_for(self, endpoint: str, **parts: Any) -> str:
        """Build a stable cache key for a search endpoint."""
        digest = self._hash_parts(**parts)
        return f"search:{endpoint}:{digest}:v1"

    def ttl_for(self, endpoint: str) -> int:
        """Return configured TTL seconds for an endpoint."""
        cfg = settings.search
        mapping = {
            "city": cfg.cache_ttl_city_sec,
            "country": cfg.cache_ttl_country_sec,
            "state": cfg.cache_ttl_state_sec,
            "user": cfg.cache_ttl_user_sec,
            "traveler": cfg.cache_ttl_traveler_sec,
            "global": cfg.cache_ttl_global_sec,
        }
        return mapping.get(endpoint, cfg.cache_ttl_global_sec)

    async def get_json(self, key: str) -> dict[str, Any] | None:
        """Read cached search JSON."""
        if not settings.redis.enabled:
            return None
        try:
            return await self._delegate.get_json(key)
        except Exception as exc:
            log_warning(logger, "Search cache get failed", key=key, error=str(exc))
            return None

    async def set_json(self, key: str, value: dict[str, Any], *, endpoint: str) -> None:
        """Store search JSON with endpoint-specific TTL."""
        if not settings.redis.enabled:
            return
        try:
            await self._delegate.set_json(key, value, ttl_sec=self.ttl_for(endpoint))
        except Exception as exc:
            log_warning(logger, "Search cache set failed", key=key, error=str(exc))

    async def get_recent_searches(self, user_id: str) -> list[str]:
        """Return recent search queries for a user."""
        if not settings.redis.enabled:
            return []
        key = f"search:recent:{user_id}"
        try:
            raw = await self._delegate.get_text(key)
        except Exception:
            return []
        if not raw:
            return []
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []

    async def push_recent_search(self, user_id: str, query: str) -> None:
        """Prepend a query to the user's recent searches list."""
        if not settings.redis.enabled or not query.strip():
            return
        key = f"search:recent:{user_id}"
        recent = await self.get_recent_searches(user_id)
        normalized = query.strip().lower()
        recent = [normalized] + [item for item in recent if item != normalized]
        recent = recent[:10]
        await self._delegate.set_text(
            key,
            json.dumps(recent),
            ttl_sec=settings.search.cache_ttl_recent_sec,
        )


search_redis_cache = SearchRedisCache()
