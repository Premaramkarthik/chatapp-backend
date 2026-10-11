"""PostgreSQL repository adapters for auth state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from asyncpg import Record

from domains.auth.models import (
    AuthSession,
    AuthSessionStatus,
    EmailVerificationToken,
    PasswordResetToken,
    SessionView,
    SigninState,
    SignupSession,
)
from domains.auth.security import now_utc
from infrastructure.database.connection import (
    call_json_function,
    execute,
    fetch,
    fetchrow,
    get_pool,
)


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
        keycloak_session_id: str,
        authenticated_at: datetime,
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
                user_agent_hash, keycloak_session_id, authenticated_at
            )
            VALUES (
                $1, $2::uuid, $3, 'ACTIVE', $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14, $15, $16
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
            keycloak_session_id,
            authenticated_at,
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
            WHERE id = $1::uuid AND status NOT IN ('REVOKED', 'COMPROMISED', 'EXPIRED')
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
        expected_version: int,
        refresh_owner: str,
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
                updated_at = now(), token_version = token_version + 1,
                refresh_owner = NULL, refresh_lease_until = NULL
            WHERE id = $1::uuid AND status = 'REFRESHING'
              AND token_version = $8 AND refresh_owner = $9::uuid
              AND refresh_lease_until > now()
            RETURNING *
            """,
            session_id,
            access_token_encrypted,
            refresh_token_encrypted,
            id_token_encrypted,
            access_expires_at,
            refresh_expires_at,
            idle_expires_at,
            expected_version,
            refresh_owner,
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
        await execute("""
            UPDATE auth_sessions
            SET status = 'EXPIRED', updated_at = now()
            WHERE status IN ('ACTIVE', 'REFRESHING')
              AND (idle_expires_at <= now() OR max_expires_at <= now())
            """)

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

    async def create_email_verification_token(
        self,
        *,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> EmailVerificationToken:
        """Persist a single-use app verification token hash."""
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE email_verification_tokens
                SET consumed_at = now()
                WHERE user_id = $1::uuid
                  AND consumed_at IS NULL
                """,
                user_id,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO email_verification_tokens (user_id, token_hash, expires_at)
                VALUES ($1::uuid, $2, $3)
                RETURNING *
                """,
                user_id,
                token_hash,
                expires_at,
            )
        return _email_verification_token_from_record(row)

    async def consume_email_verification_token(
        self,
        *,
        token_hash: str,
    ) -> EmailVerificationToken | None:
        """Consume an unexpired verification token exactly once."""
        row = await fetchrow(
            """
            UPDATE email_verification_tokens
            SET consumed_at = now()
            WHERE token_hash = $1
              AND consumed_at IS NULL
              AND expires_at > now()
            RETURNING *
            """,
            token_hash,
        )
        return None if row is None else _email_verification_token_from_record(row)

    async def get_email_verification_token(
        self,
        *,
        token_hash: str,
    ) -> EmailVerificationToken | None:
        """Return a verification token row without consuming it."""
        row = await fetchrow(
            """
            SELECT *
            FROM email_verification_tokens
            WHERE token_hash = $1
            LIMIT 1
            """,
            token_hash,
        )
        return None if row is None else _email_verification_token_from_record(row)

    async def create_password_reset_token(
        self,
        *,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> PasswordResetToken:
        """Persist a single-use app password reset token hash."""
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE password_reset_tokens
                SET consumed_at = now()
                WHERE user_id = $1::uuid
                  AND consumed_at IS NULL
                """,
                user_id,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
                VALUES ($1::uuid, $2, $3)
                RETURNING *
                """,
                user_id,
                token_hash,
                expires_at,
            )
        return _password_reset_token_from_record(row)

    async def consume_password_reset_token(
        self,
        *,
        token_hash: str,
    ) -> PasswordResetToken | None:
        """Consume an unexpired password reset token exactly once."""
        row = await fetchrow(
            """
            UPDATE password_reset_tokens
            SET consumed_at = now()
            WHERE token_hash = $1
              AND consumed_at IS NULL
              AND expires_at > now()
            RETURNING *
            """,
            token_hash,
        )
        return None if row is None else _password_reset_token_from_record(row)

    async def get_password_reset_token(
        self,
        *,
        token_hash: str,
    ) -> PasswordResetToken | None:
        """Return a password reset token row without consuming it."""
        row = await fetchrow(
            """
            SELECT *
            FROM password_reset_tokens
            WHERE token_hash = $1
            LIMIT 1
            """,
            token_hash,
        )
        return None if row is None else _password_reset_token_from_record(row)

    async def claim_refresh(self, session: AuthSession, owner: str) -> bool:
        row = await fetchrow(
            """UPDATE auth_sessions SET status='REFRESHING', refresh_owner=$2::uuid,
            refresh_lease_until=now()+interval '15 seconds'
            WHERE id=$1::uuid AND status='ACTIVE' AND token_version=$3
            RETURNING id""",
            session.id,
            owner,
            session.token_version,
        )
        return row is not None

    async def revoke_with_operation(
        self,
        *,
        user_id: str,
        subject: str,
        session_id: str | None = None,
        keep_session_id: str | None = None,
        delete_account: bool = False,
    ) -> tuple[str, list[AuthSession]]:
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT id FROM users WHERE id=$1::uuid FOR UPDATE", user_id)
            cutoff = await conn.fetchval("SELECT clock_timestamp()")
            rows = await conn.fetch(
                """UPDATE auth_sessions SET status='REVOKED', updated_at=now(),
                refresh_owner=NULL, refresh_lease_until=NULL
                WHERE user_id=$1::uuid AND status IN ('ACTIVE','REFRESHING','LOCKED')
                AND ($2::uuid IS NULL OR id=$2::uuid)
                AND ($3::uuid IS NULL OR id<>$3::uuid) AND created_at <= $4
                RETURNING *""",
                user_id,
                session_id,
                keep_session_id,
                cutoff,
            )
            if session_id and not rows:
                # Idempotent retry can still recover the original session target.
                row = await conn.fetchrow(
                    "SELECT * FROM auth_sessions WHERE id=$1::uuid AND user_id=$2::uuid",
                    session_id,
                    user_id,
                )
                if row is None:
                    raise ValueError("Session not found")
                rows = [row]
            matrix_targets = await conn.fetch(
                """SELECT DISTINCT mxid,device_id FROM (
                SELECT mxid,device_id,bff_session_id,created_at FROM matrix_sessions
                WHERE user_id=$1::uuid
                UNION ALL SELECT mxid,device_id,bff_session_id,created_at FROM matrix_login_attempts
                WHERE user_id=$1::uuid
                ) d WHERE ($2::uuid IS NULL OR bff_session_id=$2::uuid)
                AND ($3::uuid IS NULL OR bff_session_id<>$3::uuid) AND created_at<=$4""",
                user_id,
                session_id,
                keep_session_id,
                cutoff,
            )
            await conn.execute(
                """UPDATE matrix_sessions SET status='revoked' WHERE user_id=$1::uuid
                AND ($2::uuid IS NULL OR bff_session_id=$2::uuid)
                AND ($3::uuid IS NULL OR bff_session_id<>$3::uuid) AND created_at<=$4""",
                user_id,
                session_id,
                keep_session_id,
                cutoff,
            )
            preserve = None
            if keep_session_id:
                preserve = await conn.fetchval(
                    "SELECT keycloak_session_id FROM auth_sessions WHERE id=$1::uuid",
                    keep_session_id,
                )
            payload = {
                "scope": "delete_account" if delete_account else "current" if session_id else "all",
                "subject": subject,
                "user_id": user_id,
                "cutoff_ms": int(cutoff.timestamp() * 1000),
                "session_ids": sorted({r["keycloak_session_id"] for r in rows}),
                "preserve_session_id": preserve,
                "matrix_devices": [dict(target) for target in matrix_targets],
            }
            if delete_account:
                payload["matrix_account"] = await conn.fetchval(
                    "SELECT mxid FROM matrix_user_mappings WHERE user_id=$1::uuid", user_id
                )
                await conn.execute(
                    "UPDATE users SET status='deleted', updated_at=now() WHERE id=$1::uuid", user_id
                )
            op = await conn.fetchval(
                "INSERT INTO auth_remote_operations(payload) VALUES($1::jsonb) RETURNING id",
                payload,
            )
        return str(op), [_session_from_record(row) for row in rows]


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


def _email_verification_token_from_record(row: Record | None) -> EmailVerificationToken:
    if row is None:
        raise RuntimeError("Expected email verification token row")
    return EmailVerificationToken(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        token_hash=str(row["token_hash"]),
        expires_at=row["expires_at"],
        consumed_at=row["consumed_at"],
        created_at=row["created_at"],
    )


def _password_reset_token_from_record(row: Record | None) -> PasswordResetToken:
    if row is None:
        raise RuntimeError("Expected password reset token row")
    return PasswordResetToken(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        token_hash=str(row["token_hash"]),
        expires_at=row["expires_at"],
        consumed_at=row["consumed_at"],
        created_at=row["created_at"],
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
        keycloak_session_id=row["keycloak_session_id"],
        authenticated_at=row["authenticated_at"],
        token_version=row["token_version"],
        refresh_owner=str(row["refresh_owner"]) if row["refresh_owner"] else None,
        refresh_lease_until=row["refresh_lease_until"],
    )


def _session_view_from_record(row: Record) -> SessionView:
    return SessionView(
        id=str(row["id"]),
        status=AuthSessionStatus(str(row["status"])),
        device_label=row["device_label"],
        last_seen_at=row["last_seen_at"],
        created_at=row["created_at"],
    )
