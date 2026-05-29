"""Redis-backed auth session cache helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from core.config.settings import settings
from domains.auth.models import AuthSession
from infrastructure.redis.cache import auth_redis_cache


def session_cache_key(session_hash: str) -> str:
    return f"auth:session:{session_hash}"


def revoked_cache_key(session_hash: str) -> str:
    return f"auth:revoked:{session_hash}"


def refresh_lock_key(session_id: str) -> str:
    return f"auth:refresh-lock:{session_id}"


async def cache_session_snapshot(session: AuthSession, *, roles: list[str] | None = None) -> None:
    """Cache a session snapshot without extending beyond DB expiry."""
    ttl = _session_ttl(session)
    if ttl <= 0:
        return
    await auth_redis_cache.set_json(
        session_cache_key(session.session_hash),
        {
            "session_id": session.id,
            "user_id": session.user_id,
            "keycloak_sub": session.keycloak_sub,
            "status": session.status.value,
            "roles": roles or [],
            "idle_expires_at": session.idle_expires_at.isoformat(),
            "max_expires_at": session.max_expires_at.isoformat(),
        },
        ttl_sec=min(ttl, settings.auth.session_cache_ttl_sec),
    )


async def mark_session_revoked(session_hash: str) -> None:
    """Write a hot-path revoked marker."""
    await auth_redis_cache.delete(session_cache_key(session_hash))
    await auth_redis_cache.set_text(
        revoked_cache_key(session_hash),
        "1",
        ttl_sec=settings.auth.revoke_cache_ttl_sec,
    )


async def is_session_revoked(session_hash: str) -> bool:
    """Return whether a session was recently revoked."""
    return (await auth_redis_cache.get_text(revoked_cache_key(session_hash))) == "1"


async def acquire_refresh_lock(session_id: str) -> bool:
    """Acquire a short single-flight refresh lock."""
    return await auth_redis_cache.set_text(
        refresh_lock_key(session_id),
        "1",
        ttl_sec=30,
        nx=True,
    )


async def release_refresh_lock(session_id: str) -> None:
    """Release refresh lock."""
    await auth_redis_cache.delete(refresh_lock_key(session_id))


def _session_ttl(session: AuthSession) -> int:
    now = datetime.now(UTC)
    expires_at = min(session.idle_expires_at, session.max_expires_at)
    return max(0, int((expires_at - now).total_seconds()))
