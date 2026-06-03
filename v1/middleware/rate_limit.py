"""Rate limiting middleware with pluggable storage."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException, status
from starlette.types import ASGIApp, Receive, Scope, Send

from core.observability.prometheus_metrics import RATE_LIMIT_EXCEEDED_TOTAL
from infrastructure.redis.cache import auth_redis_cache
from v1.middleware.state import RATE_LIMIT_STATE_KEY, ensure_state


@dataclass(frozen=True)
class RateLimitDecision:
    """Result returned by a rate-limit store."""

    allowed: bool
    remaining: int
    retry_after_sec: int


class RateLimitStore(Protocol):
    """Storage contract used by rate limiting middleware."""

    async def hit(self, key: str, *, limit: int, window_sec: int) -> RateLimitDecision:
        """Record one request and return the rate-limit decision."""


class InMemoryRateLimitStore:
    """Process-local sliding-window store for local deployments and tests."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str, *, limit: int, window_sec: int) -> RateLimitDecision:
        now = time.monotonic()
        window_start = now - window_sec
        async with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= window_start:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(window_sec - (now - hits[0])))
                return RateLimitDecision(False, 0, retry_after)
            hits.append(now)
            return RateLimitDecision(True, max(0, limit - len(hits)), 0)


class RedisRateLimitStore:
    """Redis-backed fixed-window rate limiter with local fallback in cache facade."""

    async def hit(self, key: str, *, limit: int, window_sec: int) -> RateLimitDecision:
        redis_key = f"rate:{key}:{int(time.time() // window_sec)}"
        count = await auth_redis_cache.increment(redis_key, ttl_sec=window_sec)
        if count > limit:
            return RateLimitDecision(False, 0, window_sec)
        return RateLimitDecision(True, max(0, limit - count), 0)


class RateLimitMiddleware:
    """Apply lightweight request rate limiting before expensive work."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        store: RateLimitStore,
        limit: int,
        window_sec: int,
        excluded_paths: set[str],
    ) -> None:
        self.app = app
        self.store = store
        self.limit = limit
        self.window_sec = window_sec
        self.excluded_paths = excluded_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.excluded_paths:
            await self.app(scope, receive, send)
            return

        decision = await self.store.hit(
            _rate_limit_key(scope),
            limit=self.limit,
            window_sec=self.window_sec,
        )
        ensure_state(scope)[RATE_LIMIT_STATE_KEY] = decision
        if not decision.allowed:
            RATE_LIMIT_EXCEEDED_TOTAL.labels(path=scope["path"]).inc()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={
                    "Retry-After": str(decision.retry_after_sec),
                    "X-RateLimit-Limit": str(self.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        await self.app(scope, receive, send)


def _rate_limit_key(scope: Scope) -> str:
    client = scope.get("client")
    client_host = client[0] if client else "unknown"
    return f"{client_host}:{scope['path']}"
