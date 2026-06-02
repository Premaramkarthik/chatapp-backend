"""PostgreSQL repository adapters for auth state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from asyncpg import Record

from domains.auth.models import (
    AuthSession,
    AuthSessionStatus,
    SessionView,
    SigninState,
    SignupSession,
)
from domains.auth.security import now_utc
from infrastructure.database.connection import call_json_function, execute, fetch, fetchrow


class PostgresAuthRepository:
    """Persistence adapter for signin state, BFF sessions, and auth audit events."""

    async def create_signin_state(
        self,
        *,
        state_hash: str,
        nonce_hash: str,
        code_verifier_encrypted: str,
        client_id: str,
        redirect_uri: str,
        post_signin_redirect_uri: str,
        expires_at: datetime,
        flow_type: str = "signin",
        account_mode: str | None = None,
        identity_provider: str | None = None,
        email_hash: str | None = None,
    ) -> SigninState:
        row = await fetchrow(
            """
            INSERT INTO oauth_signin_states (
                state_hash,
                nonce_hash,
                code_verifier_encrypted,
                client_id,
                redirect_uri,
                post_signin_redirect_uri,
                expires_at,
                flow_type,
                account_mode,
                identity_provider,
                email_hash
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING *
            """,
            state_hash,
            nonce_hash,
            code_verifier_encrypted,
            client_id,
            redirect_uri,
            post_signin_redirect_uri,
            expires_at,
            flow_type,
            account_mode,
            identity_provider,
            email_hash,
        )
        return _signin_state_from_record(row)

    async def consume_signin_state(self, *, state_hash: str) -> SigninState | None:
        row = await fetchrow(
            """
            UPDATE oauth_signin_states
            SET consumed_at = now()
            WHERE state_hash = $1
              AND consumed_at IS NULL
              AND expires_at > now()
            RETURNING *
            """,
            state_hash,
        )
        return None if row is None else _signin_state_from_record(row)

    async def create_session(
        self,
        *,
        session_hash: str,
        user_id: str,
        keycloak_sub: str,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        id_token_encrypted: str | None,
        access_expires_at: datetime,
        refresh_expires_at: datetime | None,
        idle_expires_at: datetime,
        max_expires_at: datetime,
        csrf_token_hash: str | None,
        device_label: str | None,
        ip_hash: str | None,
        user_agent_hash: str | None,
    ) -> AuthSession:
        row = await fetchrow(
            """
            INSERT INTO auth_sessions (
                session_hash,
                user_id,
                keycloak_sub,
                status,
                access_token_encrypted,
                refresh_token_encrypted,
                id_token_encrypted,
                access_expires_at,
                refresh_expires_at,
                idle_expires_at,
                max_expires_at,
                csrf_token_hash,
                device_label,
                ip_hash,
                user_agent_hash
            )
            VALUES (
                $1, $2::uuid, $3, 'ACTIVE', $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
            )
            RETURNING *
            """,
            session_hash,
            user_id,
            keycloak_sub,
            access_token_encrypted,
            refresh_token_encrypted,
            id_token_encrypted,
            access_expires_at,
            refresh_expires_at,
            idle_expires_at,
            max_expires_at,
            csrf_token_hash,
            device_label,
            ip_hash,
            user_agent_hash,
        )
        return _session_from_record(row)

    async def get_session_by_hash(self, session_hash: str) -> AuthSession | None:
        row = await fetchrow(
            """
            SELECT *
            FROM auth_sessions
            WHERE session_hash = $1
            LIMIT 1
            """,
            session_hash,
        )
        return None if row is None else _session_from_record(row)

    async def mark_session_status(
        self,
        *,
        session_id: str,
        status: AuthSessionStatus,
    ) -> AuthSession | None:
        row = await fetchrow(
            """
            UPDATE auth_sessions
            SET status = $2, updated_at = now()
            WHERE id = $1::uuid
            RETURNING *
            """,
            session_id,
            status.value,
        )
        return None if row is None else _session_from_record(row)

    async def touch_session(self, *, session_id: str, idle_expires_at: datetime) -> None:
        await execute(
            """
            UPDATE auth_sessions
            SET last_seen_at = now(), idle_expires_at = $2, updated_at = now()
            WHERE id = $1::uuid AND status = 'ACTIVE'
            """,
            session_id,
            idle_expires_at,
        )

    async def update_session_tokens(
        self,
        *,
        session_id: str,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        id_token_encrypted: str | None,
        access_expires_at: datetime,
        refresh_expires_at: datetime | None,
        idle_expires_at: datetime,
    ) -> AuthSession | None:
        row = await fetchrow(
            """
            UPDATE auth_sessions
            SET status = 'ACTIVE',
                access_token_encrypted = $2,
                refresh_token_encrypted = COALESCE($3, refresh_token_encrypted),
                id_token_encrypted = COALESCE($4, id_token_encrypted),
                access_expires_at = $5,
                refresh_expires_at = COALESCE($6, refresh_expires_at),
                idle_expires_at = $7,
                last_seen_at = now(),
                updated_at = now()
            WHERE id = $1::uuid
            RETURNING *
            """,
            session_id,
            access_token_encrypted,
            refresh_token_encrypted,
            id_token_encrypted,
            access_expires_at,
            refresh_expires_at,
            idle_expires_at,
        )
        return None if row is None else _session_from_record(row)

    async def list_sessions(self, *, user_id: str) -> list[SessionView]:
        rows = await fetch(
            """
            SELECT id, status, device_label, last_seen_at, created_at
            FROM auth_sessions
            WHERE user_id = $1::uuid
              AND status IN ('ACTIVE', 'REFRESHING', 'LOCKED')
              AND max_expires_at > now()
            ORDER BY last_seen_at DESC
            """,
            user_id,
        )
        return [_session_view_from_record(row) for row in rows]

    async def revoke_session(
        self,
        *,
        session_id: str,
        user_id: str,
        status: AuthSessionStatus = AuthSessionStatus.REVOKED,
    ) -> AuthSession | None:
        row = await fetchrow(
            """
            UPDATE auth_sessions
            SET status = $3, updated_at = now()
            WHERE id = $1::uuid
              AND user_id = $2::uuid
              AND status IN ('ACTIVE', 'REFRESHING', 'LOCKED')
            RETURNING *
            """,
            session_id,
            user_id,
            status.value,
        )
        return None if row is None else _session_from_record(row)

    async def revoke_all_sessions(
        self,
        *,
        user_id: str,
        keep_session_id: str | None = None,
    ) -> list[AuthSession]:
        rows = await fetch(
            """
            UPDATE auth_sessions
            SET status = 'REVOKED', updated_at = now()
            WHERE user_id = $1::uuid
              AND status IN ('ACTIVE', 'REFRESHING', 'LOCKED')
              AND ($2::uuid IS NULL OR id <> $2::uuid)
            RETURNING *
            """,
            user_id,
            keep_session_id,
        )
        return [_session_from_record(row) for row in rows]

    async def record_event(
        self,
        *,
        event_type: str,
        user_id: str | None = None,
        keycloak_sub: str | None = None,
        email_hash: str | None = None,
        ip_hash: str | None = None,
        user_agent_hash: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await execute(
            """
            INSERT INTO auth_security_events (
                event_type,
                user_id,
                keycloak_sub,
                email_hash,
                ip_hash,
                user_agent_hash,
                request_id,
                metadata
            )
            VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8::jsonb)
            """,
            event_type,
            user_id,
            keycloak_sub,
            email_hash,
            ip_hash,
            user_agent_hash,
            request_id,
            metadata or {},
        )

    async def get_idempotency_result(
        self,
        *,
        idempotency_key_hash: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        """Return a stored idempotent response for a matching request."""
        row = await fetchrow(
            """
            SELECT request_hash, response_body
            FROM auth_idempotency_keys
            WHERE idempotency_key_hash = $1
              AND expires_at > now()
            LIMIT 1
            """,
            idempotency_key_hash,
        )
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            return {"error": "idempotency_key_reused"}
        return dict(row["response_body"])

    async def store_idempotency_result(
        self,
        *,
        idempotency_key_hash: str,
        request_hash: str,
        response_body: dict[str, Any],
        status_code: int,
        email_hash: str | None,
        expires_at: datetime,
    ) -> None:
        """Store an idempotent signup response."""
        await execute(
            """
            INSERT INTO auth_idempotency_keys (
                idempotency_key_hash,
                request_hash,
                response_body,
                status_code,
                email_hash,
                expires_at
            )
            VALUES ($1, $2, $3::jsonb, $4, $5, $6)
            ON CONFLICT (idempotency_key_hash) DO NOTHING
            """,
            idempotency_key_hash,
            request_hash,
            response_body,
            status_code,
            email_hash,
            expires_at,
        )

    async def write_outbox_event(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        """Persist an auth lifecycle event for future publication."""
        await execute(
            """
            INSERT INTO auth_outbox_events (
                event_type,
                aggregate_type,
                aggregate_id,
                payload
            )
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            event_type,
            aggregate_type,
            aggregate_id,
            payload,
        )

    async def expire_old_sessions(self) -> None:
        """Mark old sessions expired. Intended for maintenance jobs."""
        await execute(
            """
            UPDATE auth_sessions
            SET status = 'EXPIRED', updated_at = now()
            WHERE status IN ('ACTIVE', 'REFRESHING')
              AND (idle_expires_at <= now() OR max_expires_at <= now())
            """
        )

    async def create_signup_session(
        self,
        *,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> SignupSession:
        """Persist a signup session token hash for step 2 completion."""
        row = await call_json_function(
            "fn_signup_sessions",
            1,
            {
                "user_id": user_id,
                "token_hash": token_hash,
                "expires_at": expires_at.isoformat(),
            },
        )
        return _signup_session_from_mapping(row)

    async def resolve_signup_session(self, *, token_hash: str) -> SignupSession | None:
        """Return an active signup session for the given token hash."""
        row = await call_json_function("fn_signup_sessions", 2, {"token_hash": token_hash})
        return None if row is None else _signup_session_from_mapping(row)

    async def complete_signup_session(self, *, session_id: str) -> SignupSession | None:
        """Mark a signup session complete after profile step."""
        row = await call_json_function("fn_signup_sessions", 3, {"session_id": session_id})
        return None if row is None else _signup_session_from_mapping(row)


def _signup_session_from_mapping(data: dict) -> SignupSession:
    return SignupSession(
        id=str(data["id"]),
        user_id=str(data["user_id"]),
        token_hash=str(data["token_hash"]),
        step_completed=int(data["step_completed"]),
        expires_at=data["expires_at"],
        revoked_at=data.get("revoked_at"),
        created_at=data.get("created_at"),
    )


def _signin_state_from_record(row: Record | None) -> SigninState:
    if row is None:
        raise RuntimeError("Expected signin state row")
    return SigninState(
        id=str(row["id"]),
        state_hash=str(row["state_hash"]),
        nonce_hash=str(row["nonce_hash"]),
        code_verifier_encrypted=str(row["code_verifier_encrypted"]),
        redirect_uri=str(row["redirect_uri"]),
        post_signin_redirect_uri=str(row["post_signin_redirect_uri"]),
        expires_at=row["expires_at"],
        consumed_at=row["consumed_at"],
        flow_type=str(row["flow_type"]) if "flow_type" in row else "signin",
        account_mode=row["account_mode"] if "account_mode" in row else None,
        identity_provider=row["identity_provider"] if "identity_provider" in row else None,
        email_hash=row["email_hash"] if "email_hash" in row else None,
    )


def _session_from_record(row: Record | None) -> AuthSession:
    if row is None:
        raise RuntimeError("Expected auth session row")
    status = AuthSessionStatus(str(row["status"]))
    return AuthSession(
        id=str(row["id"]),
        session_hash=str(row["session_hash"]),
        user_id=str(row["user_id"]),
        keycloak_sub=str(row["keycloak_sub"]),
        status=status,
        access_token_encrypted=str(row["access_token_encrypted"]),
        refresh_token_encrypted=row["refresh_token_encrypted"],
        id_token_encrypted=row["id_token_encrypted"],
        access_expires_at=row["access_expires_at"],
        refresh_expires_at=row["refresh_expires_at"],
        idle_expires_at=row["idle_expires_at"],
        max_expires_at=row["max_expires_at"],
        csrf_token_hash=row["csrf_token_hash"],
        device_label=row["device_label"],
        ip_hash=row["ip_hash"],
        user_agent_hash=row["user_agent_hash"],
        last_seen_at=row["last_seen_at"] or now_utc(),
        created_at=row["created_at"],
    )


def _session_view_from_record(row: Record) -> SessionView:
    return SessionView(
        id=str(row["id"]),
        status=AuthSessionStatus(str(row["status"])),
        device_label=row["device_label"],
        last_seen_at=row["last_seen_at"],
        created_at=row["created_at"],
    )
