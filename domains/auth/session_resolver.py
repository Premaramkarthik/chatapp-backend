"""Resolve BFF session cookies into request principals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.config.settings import settings
from core.observability.metrics import metrics_registry
from domains.auth.keycloak_client import keycloak_auth_client
from domains.auth.models import AuthSession, AuthSessionStatus
from domains.auth.security import TokenCipher, hash_secret
from domains.auth.session_cache import (
    acquire_refresh_lock,
    cache_session_snapshot,
    is_session_revoked,
    release_refresh_lock,
)
from infrastructure.database.repositories.auth import PostgresAuthRepository
from infrastructure.keycloak.adapter import keycloak_verifier
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.base import AuthenticationError


class AuthSessionResolver:
    """Resolve and refresh server-side sessions."""

    def __init__(
        self,
        *,
        repository: PostgresAuthRepository | None = None,
        cipher: TokenCipher | None = None,
    ) -> None:
        self._repository = repository or PostgresAuthRepository()
        self._cipher = cipher or TokenCipher()

    async def resolve(self, session_token: str) -> tuple[KeycloakPrincipal, AuthSession]:
        """Resolve an opaque session cookie into a Keycloak principal and auth session."""
        session_hash = hash_secret(session_token)
        if await is_session_revoked(session_hash):
            raise AuthenticationError("Authentication session has been revoked")

        session = await self._repository.get_session_by_hash(session_hash)
        if session is None:
            raise AuthenticationError("Authentication session not found")
        if not session.is_usable:
            raise AuthenticationError("Authentication session is not active")
        now = datetime.now(UTC)
        if session.idle_expires_at <= now or session.max_expires_at <= now:
            await self._repository.mark_session_status(
                session_id=session.id,
                status=AuthSessionStatus.EXPIRED,
            )
            raise AuthenticationError("Authentication session expired")

        session = await self._refresh_if_needed(session)
        access_token = self._cipher.decrypt(session.access_token_encrypted)
        if access_token is None:
            raise AuthenticationError("Authentication session is missing an access token")
        principal = await keycloak_verifier.verify_token(access_token)
        await self._repository.touch_session(
            session_id=session.id,
            idle_expires_at=min(
                datetime.now(UTC) + timedelta(seconds=settings.auth.session_idle_sec),
                session.max_expires_at,
            ),
        )
        await cache_session_snapshot(session, roles=principal.roles)
        return principal, session

    async def _refresh_if_needed(self, session: AuthSession) -> AuthSession:
        refresh_at = datetime.now(UTC) + timedelta(seconds=settings.auth.refresh_leeway_sec)
        if session.access_expires_at > refresh_at:
            return session

        refresh_token = self._cipher.decrypt(session.refresh_token_encrypted)
        if refresh_token is None:
            return session
        if not await acquire_refresh_lock(session.id):
            return session

        try:
            await self._repository.mark_session_status(
                session_id=session.id,
                status=AuthSessionStatus.REFRESHING,
            )
            token_set = await keycloak_auth_client.refresh(refresh_token=refresh_token)
            updated = await self._repository.update_session_tokens(
                session_id=session.id,
                access_token_encrypted=str(self._cipher.encrypt(token_set.access_token)),
                refresh_token_encrypted=self._cipher.encrypt(token_set.refresh_token),
                id_token_encrypted=self._cipher.encrypt(token_set.id_token),
                access_expires_at=token_set.expires_at,
                refresh_expires_at=token_set.refresh_expires_at,
                idle_expires_at=min(
                    datetime.now(UTC) + timedelta(seconds=settings.auth.session_idle_sec),
                    session.max_expires_at,
                ),
            )
            return updated or session
        except Exception:
            metrics_registry.increment("auth_refresh_failure_total", reason="refresh_exception")
            await self._repository.mark_session_status(
                session_id=session.id,
                status=AuthSessionStatus.COMPROMISED,
            )
            raise
        finally:
            await release_refresh_lock(session.id)


auth_session_resolver = AuthSessionResolver()
