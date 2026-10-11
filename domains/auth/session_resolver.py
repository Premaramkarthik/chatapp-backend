"""Fail-closed session resolution with PostgreSQL single-flight refresh."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException

from core.config.settings import settings
from domains.auth.keycloak_client import keycloak_auth_client
from domains.auth.models import AuthSession, AuthSessionStatus
from domains.auth.security import TokenCipher, hash_secret
from infrastructure.database.repositories.auth import PostgresAuthRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from infrastructure.keycloak.adapter import keycloak_verifier
from infrastructure.keycloak.session_control import session_control
from v1.utils.base import AuthenticationError


class AuthSessionResolver:
    def __init__(self, *, repository=None, cipher=None):
        self._repository = repository or PostgresAuthRepository()
        self._cipher = cipher or TokenCipher()

    async def resolve(self, session_token: str):
        session = await self.resolve_for_revocation(session_token)
        session = await self._refresh_if_needed(session)
        token = self._cipher.decrypt(session.access_token_encrypted)
        if not token:
            raise AuthenticationError("Missing session token")
        principal = await keycloak_verifier.verify_token(token)
        if principal.sid != session.keycloak_session_id:
            raise AuthenticationError("Session identity changed")
        await session_control.check(principal)
        latest = await self._repository.get_session_by_hash(session.session_hash)
        if latest is None or not latest.is_usable:
            raise AuthenticationError("Authentication session was revoked")
        await self._repository.touch_session(
            session_id=session.id,
            idle_expires_at=min(
                datetime.now(UTC) + timedelta(seconds=settings.auth.session_idle_sec),
                session.max_expires_at,
            ),
        )
        return principal, latest

    async def resolve_for_revocation(self, session_token: str) -> AuthSession:
        """Authenticate ownership locally so provider outages cannot prevent logout."""
        session = await self._repository.get_session_by_hash(hash_secret(session_token))
        if session is None or not session.is_usable:
            raise AuthenticationError("Authentication session is not active")
        now = datetime.now(UTC)
        if min(session.idle_expires_at, session.max_expires_at) <= now:
            await self._repository.mark_session_status(
                session_id=session.id, status=AuthSessionStatus.EXPIRED
            )
            raise AuthenticationError("Authentication session expired")
        user = await PostgresUserRepository().get_by_id(session.user_id)
        if user is None or user.status not in {"active", "pending_profile_setup"}:
            raise AuthenticationError("Account is disabled")
        return session

    async def _refresh_if_needed(self, session: AuthSession) -> AuthSession:
        if session.status == AuthSessionStatus.ACTIVE and session.access_expires_at > datetime.now(
            UTC
        ) + timedelta(seconds=settings.auth.refresh_leeway_sec):
            return session
        owner = str(uuid4())
        if not await self._repository.claim_refresh(session, owner):
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                latest = await self._repository.get_session_by_hash(session.session_hash)
                if latest is None or not latest.is_usable:
                    raise AuthenticationError("Session revoked during refresh")
                if (
                    latest.status == AuthSessionStatus.ACTIVE
                    and latest.token_version > session.token_version
                ):
                    return latest
                if latest.refresh_lease_until and latest.refresh_lease_until <= datetime.now(UTC):
                    await self._repository.mark_session_status(
                        session_id=latest.id, status=AuthSessionStatus.LOCKED
                    )
                    raise AuthenticationError(
                        "Refresh outcome unknown; sign in again", code="reauthentication_required"
                    )
            raise HTTPException(
                503, detail={"code": "session_refresh_pending"}, headers={"Retry-After": "2"}
            )
        refresh_token = self._cipher.decrypt(session.refresh_token_encrypted)
        try:
            if not refresh_token:
                raise AuthenticationError("Missing refresh token")
            tokens = await keycloak_auth_client.refresh(refresh_token=refresh_token)
            principal = await keycloak_verifier.verify_token(tokens.access_token)
            if principal.sid != session.keycloak_session_id:
                raise AuthenticationError("Session credentials changed")
            await session_control.check(principal)
            latest = await self._repository.update_session_tokens(
                session_id=session.id,
                access_token_encrypted=self._cipher.encrypt(tokens.access_token),
                refresh_token_encrypted=self._cipher.encrypt(tokens.refresh_token),
                id_token_encrypted=self._cipher.encrypt(tokens.id_token),
                access_expires_at=tokens.expires_at,
                refresh_expires_at=tokens.refresh_expires_at,
                idle_expires_at=min(
                    datetime.now(UTC) + timedelta(seconds=settings.auth.session_idle_sec),
                    session.max_expires_at,
                ),
                expected_version=session.token_version,
                refresh_owner=owner,
            )
            if latest is None:
                raise AuthenticationError("Session revoked during refresh")
            return latest
        except AuthenticationError:
            await self._repository.mark_session_status(
                session_id=session.id, status=AuthSessionStatus.REVOKED
            )
            raise
        except Exception as exc:
            # A request may have reached the provider: never blindly reuse a rotating token.
            await self._repository.mark_session_status(
                session_id=session.id, status=AuthSessionStatus.LOCKED
            )
            raise AuthenticationError(
                "Refresh outcome unknown; sign in again", code="reauthentication_required"
            ) from exc


auth_session_resolver = AuthSessionResolver()
