"""Redis cache helpers with safe in-process fallback."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from core.config.settings import settings
from core.logging.logger import get_logger, log_info, log_warning
from core.observability.prometheus_metrics import AUTH_REDIS_FALLBACK_TOTAL

logger = get_logger(__name__)

try:  # pragma: no cover - import branch depends on installed optional runtime package
    import redis.asyncio as redis_async
except Exception:  # pragma: no cover
    redis_async = None


@dataclass
class _MemoryValue:
    value: str
    expires_at: float | None


class InMemoryRedisFallback:
    """Small async fallback used when Redis is disabled or unavailable."""

    def __init__(self) -> None:
        self._values: dict[str, _MemoryValue] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        async with self._lock:
            value = self._values.get(key)
            if value is None:
                return None
            if value.expires_at is not None and value.expires_at <= time.time():
                self._values.pop(key, None)
                return None
            return value.value

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
        async with self._lock:
            existing = self._values.get(key)
            if (
                existing is not None
                and existing.expires_at is not None
                and existing.expires_at <= time.time()
            ):
                self._values.pop(key, None)
                existing = None
            if nx and existing is not None:
                return False
            expires_at = None if ex is None else time.time() + ex
            self._values[key] = _MemoryValue(value=value, expires_at=expires_at)
            return True

    async def delete(self, *keys: str) -> int:
        async with self._lock:
            count = 0
            for key in keys:
                if key in self._values:
                    count += 1
                    self._values.pop(key, None)
            return count

    async def incr(self, key: str) -> int:
        async with self._lock:
            existing = self._values.get(key)
            if (
                existing is not None
                and existing.expires_at is not None
                and existing.expires_at <= time.time()
            ):
                self._values.pop(key, None)
                existing = None
            current = existing.value if existing else None
            value = int(current or "0") + 1
            self._values[key] = _MemoryValue(
                value=str(value),
                expires_at=existing.expires_at if existing else None,
            )
            return value

    async def expire(self, key: str, seconds: int) -> bool:
        async with self._lock:
            if key not in self._values:
                return False
            self._values[key].expires_at = time.time() + seconds
            return True

    async def close(self) -> None:
        """Match redis-py's async close API."""


class AuthRedisCache:
    """JSON/string cache facade used by auth, JWKS, and rate limiting."""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._fallback = InMemoryRedisFallback()
        self._lock = asyncio.Lock()

    async def client(self) -> Any:
        """Return Redis client or fallback, initialized lazily."""
        if not settings.redis.enabled or redis_async is None:
            return self._fallback
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                self._client = redis_async.from_url(
                    settings.redis.url,
                    socket_timeout=settings.redis.socket_timeout_sec,
                    socket_connect_timeout=settings.redis.connect_timeout_sec,
                    decode_responses=True,
                )
            return self._client

    async def get_text(self, key: str) -> str | None:
        """Read a string value."""
        try:
            client = await self.client()
            return await client.get(key)
        except Exception as exc:
            AUTH_REDIS_FALLBACK_TOTAL.labels(reason=type(exc).__name__).inc()
            log_warning(
                logger,
                "Redis get failed; using in-memory fallback",
                key=key,
                error_type=type(exc).__name__,
            )
            return await self._fallback.get(key)

    async def set_text(
        self,
        key: str,
        value: str,
        *,
        ttl_sec: int | None = None,
        nx: bool = False,
    ) -> bool:
        """Write a string value with optional TTL and NX semantics."""
        try:
            client = await self.client()
            return bool(await client.set(key, value, ex=ttl_sec, nx=nx))
        except Exception as exc:
            AUTH_REDIS_FALLBACK_TOTAL.labels(reason=type(exc).__name__).inc()
            log_warning(
                logger,
                "Redis set failed; using in-memory fallback",
                key=key,
                error_type=type(exc).__name__,
            )
            return await self._fallback.set(key, value, ex=ttl_sec, nx=nx)

    async def get_json(self, key: str) -> dict[str, Any] | None:
        """Read a JSON object."""
        value = await self.get_text(key)
        if value is None:
            return None
        return json.loads(value)

    async def set_json(self, key: str, value: dict[str, Any], *, ttl_sec: int) -> bool:
        """Write a JSON object."""
        return await self.set_text(key, json.dumps(value, default=str), ttl_sec=ttl_sec)

    async def delete(self, *keys: str) -> int:
        """Delete cache keys."""
        try:
            client = await self.client()
            return int(await client.delete(*keys))
        except Exception as exc:
            AUTH_REDIS_FALLBACK_TOTAL.labels(reason=type(exc).__name__).inc()
            log_warning(
                logger,
                "Redis delete failed; using in-memory fallback",
                error_type=type(exc).__name__,
            )
            return await self._fallback.delete(*keys)

    async def increment(self, key: str, *, ttl_sec: int) -> int:
        """Increment a counter and set TTL on first hit."""
        try:
            client = await self.client()
            value = int(await client.incr(key))
            if value == 1:
                await client.expire(key, ttl_sec)
            return value
        except Exception as exc:
            AUTH_REDIS_FALLBACK_TOTAL.labels(reason=type(exc).__name__).inc()
            log_warning(
                logger,
                "Redis increment failed; using in-memory fallback",
                key=key,
                error_type=type(exc).__name__,
            )
            value = await self._fallback.incr(key)
            if value == 1:
                await self._fallback.expire(key, ttl_sec)
            return value

    async def close(self) -> None:
        """Close Redis connection if one was opened."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


auth_redis_cache = AuthRedisCache()


class GeoRedisCache:
    """Search-keyed geo autocomplete cache with structured usage logging."""

    def __init__(self, delegate: AuthRedisCache | None = None) -> None:
        self._delegate = delegate or auth_redis_cache
        self._logger = get_logger(__name__)

    @staticmethod
    def search_key(resource: str, *, limit: int, search: str, parent_id: int | None = None) -> str:
        """Build a stable cache key for autocomplete queries."""
        import hashlib

        parts = {"limit": limit, "search": search.strip().lower()}
        if parent_id is not None:
            if resource == "states":
                parts["country_id"] = parent_id
            elif resource == "cities":
                parts["state_id"] = parent_id
        normalized = "|".join(f"{k}={v}" for k, v in sorted(parts.items()))
        digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        if resource == "countries":
            return f"geo:countries:search:{digest}:v1"
        if resource == "states":
            return f"geo:states:country:{parent_id}:search:{digest}:v1"
        return f"geo:cities:state:{parent_id}:search:{digest}:v1"

    def _log_enabled(self) -> bool:
        from core.config.settings import settings

        return settings.geo.cache_log_enabled

    async def get_json(self, key: str, *, resource: str) -> list[dict[str, Any]] | None:
        """Read cached geo search results."""
        from core.config.settings import settings

        if not settings.geo.cache_enabled:
            return None
        prefix = key.rsplit(":", 1)[0] if key.endswith(":v1") else key[:48]
        used_fallback = False
        try:
            client = await self._delegate.client()
            used_fallback = client is self._delegate._fallback
            raw = await self._delegate.get_text(key)
        except Exception as exc:
            if self._log_enabled():
                log_warning(
                    self._logger,
                    "Geo Redis failed; using in-memory fallback",
                    operation="get",
                    error_type=type(exc).__name__,
                    cache_key_prefix=prefix,
                    namespace="geo",
                    resource=resource,
                )
            raw = await self._delegate._fallback.get(key)
            used_fallback = True
        backend = "memory_fallback" if used_fallback else "redis"
        if raw is None:
            if self._log_enabled():
                log_info(
                    self._logger,
                    "Geo cache miss",
                    backend=backend,
                    operation="get",
                    namespace="geo",
                    resource=resource,
                    result="miss",
                    cache_key_prefix=prefix,
                )
            return None
        if self._log_enabled():
            log_info(
                self._logger,
                "Geo cache hit",
                backend=backend,
                operation="get",
                namespace="geo",
                resource=resource,
                cache_key_prefix=prefix,
            )
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else None

    async def set_json(
        self,
        key: str,
        value: list[dict[str, Any]],
        *,
        resource: str,
        ttl_sec: int,
    ) -> None:
        """Store geo search results."""
        from core.config.settings import settings

        if not settings.geo.cache_enabled:
            return
        prefix = key.rsplit(":", 1)[0] if key.endswith(":v1") else key[:48]
        used_fallback = False
        try:
            client = await self._delegate.client()
            used_fallback = client is self._delegate._fallback
            await self._delegate.set_text(key, json.dumps(value, default=str), ttl_sec=ttl_sec)
        except Exception as exc:
            if self._log_enabled():
                log_warning(
                    self._logger,
                    "Geo Redis failed; using in-memory fallback",
                    operation="set",
                    error_type=type(exc).__name__,
                    cache_key_prefix=prefix,
                    namespace="geo",
                    resource=resource,
                )
            await self._delegate._fallback.set(
                key,
                json.dumps(value, default=str),
                ex=ttl_sec,
            )
            used_fallback = True
        if self._log_enabled():
            log_info(
                self._logger,
                "Geo cache stored",
                backend="memory_fallback" if used_fallback else "redis",
                operation="set",
                namespace="geo",
                resource=resource,
                ttl_sec=ttl_sec,
                cache_key_prefix=prefix,
            )

    async def flush_all(self) -> int:
        """Delete all geo:* cache keys."""
        deleted = 0
        try:
            client = await self._delegate.client()
            if hasattr(client, "scan_iter"):
                keys = [key async for key in client.scan_iter("geo:*", count=200)]
                if keys:
                    deleted = int(await client.delete(*keys))
            else:
                deleted = await self._delegate._fallback.delete()
        except Exception as exc:
            log_warning(
                self._logger,
                "Geo Redis failed; using in-memory fallback",
                operation="flush",
                error_type=type(exc).__name__,
                namespace="geo",
            )
        if self._log_enabled():
            log_info(
                self._logger,
                "Geo cache flushed",
                operation="flush",
                namespace="geo",
                keys_deleted=deleted,
                pattern="geo:*",
            )
        return deleted


geo_redis_cache = GeoRedisCache()
