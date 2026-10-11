"""PostgreSQL users repository adapter."""

from __future__ import annotations

from domains.users.repository import UserRepository
from domains.users.user import BootstrapUserCommand, User
from infrastructure.database.connection import call_json_function, get_pool
from v1.utils.base import AuthenticationError


class PostgresUserRepository(UserRepository):
    """PostgreSQL adapter for users domain persistence."""

    async def resolve_verified_identity(
        self, *, subject: str, email: str, display_name: str | None, created_via: str
    ) -> User:
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            # Serializes first-login claims of the same normalized address.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", email)
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE keycloak_sub=$1 FOR UPDATE", subject
            )
            if row is None:
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE lower(email)=$1 FOR UPDATE", email
                )
                if row is not None and row["keycloak_sub"] not in {None, subject}:
                    raise AuthenticationError(
                        "Account linking confirmation required", code="account_linking_required"
                    )
                if row is None:
                    row = await conn.fetchrow(
                        """INSERT INTO users(
                            keycloak_sub,email,display_name,status,email_verified,created_via)
                        VALUES($1,$2,$3,'pending_profile_setup',true,$4) RETURNING *""",
                        subject,
                        email,
                        display_name,
                        created_via,
                    )
                else:
                    row = await conn.fetchrow(
                        """UPDATE users SET keycloak_sub=$2,email_verified=true,
                        status=CASE WHEN status='pending_verification'
                            THEN 'pending_profile_setup' ELSE status END
                        WHERE id=$1 AND (keycloak_sub IS NULL OR keycloak_sub=$2) RETURNING *""",
                        row["id"],
                        subject,
                    )
            if row is None or row["status"] not in {"active", "pending_profile_setup"}:
                raise AuthenticationError("Account is disabled")
            return User.from_mapping(dict(row))

    async def bootstrap(self, command: BootstrapUserCommand) -> User:
        """Create or return the local user row for an authenticated principal."""
        row = await call_json_function(
            "fn_users",
            1,
            {
                "keycloak_sub": command.keycloak_sub,
                "email": command.email,
                "display_name": command.display_name,
            },
        )
        return User.from_mapping(row)

    async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
        """Return a local user by Keycloak subject."""
        row = await call_json_function("fn_users", 3, {"keycloak_sub": keycloak_sub})
        return None if row is None else User.from_mapping(row)

    async def get_by_id(self, user_id: str) -> User | None:
        """Return a local user by id."""
        row = await call_json_function("fn_users", 2, {"user_id": user_id})
        return None if row is None else User.from_mapping(row)

    async def update_account_mode(self, *, keycloak_sub: str, account_mode: str) -> User:
        """Update business account mode without changing Keycloak roles."""
        row = await call_json_function(
            "fn_users",
            5,
            {
                "keycloak_sub": keycloak_sub,
                "account_mode": account_mode,
            },
        )
        return User.from_mapping(row)

    async def update_display_name(self, *, user_id: str, display_name: str) -> User | None:
        """Update display name for an existing user."""
        row = await call_json_function(
            "fn_users",
            4,
            {
                "user_id": user_id,
                "display_name": display_name,
            },
        )
        return None if row is None else User.from_mapping(row)

    async def get_by_email(self, email: str) -> User | None:
        """Return a local user by normalized email."""
        row = await call_json_function("fn_users", 6, {"email": email})
        return None if row is None else User.from_mapping(row)

    async def create_pending_signup(
        self,
        *,
        email: str,
        display_name: str | None = None,
        account_mode: str | None = None,
        created_via: str,
    ) -> User:
        """Create or return a pending signup user before calling Keycloak."""
        row = await call_json_function(
            "fn_users",
            7,
            {
                "email": email,
                "display_name": display_name or "",
                "account_mode": account_mode or "",
                "created_via": created_via,
            },
        )
        return User.from_mapping(row)

    async def complete_signup_profile(
        self,
        *,
        user_id: str,
        display_name: str,
        account_mode: str,
    ) -> User | None:
        """Complete signup profile fields for a pending user."""
        row = await call_json_function(
            "fn_users",
            12,
            {
                "user_id": user_id,
                "display_name": display_name,
                "account_mode": account_mode,
            },
        )
        return None if row is None else User.from_mapping(row)

    async def link_keycloak_subject(self, *, user_id: str, keycloak_sub: str) -> User:
        """Link a pending user to a Keycloak subject."""
        row = await call_json_function(
            "fn_users",
            8,
            {
                "user_id": user_id,
                "keycloak_sub": keycloak_sub,
            },
        )
        return User.from_mapping(row)

    async def mark_verification_sent(self, *, user_id: str) -> User:
        """Record a verification/setup email send."""
        row = await call_json_function("fn_users", 9, {"user_id": user_id})
        return User.from_mapping(row)

    async def activate_after_verified_signin(
        self,
        *,
        keycloak_sub: str,
        email: str,
        email_verified: bool,
    ) -> User | None:
        """Activate or move a pending user after verified Keycloak signin."""
        row = await call_json_function(
            "fn_users",
            10,
            {
                "keycloak_sub": keycloak_sub,
                "email": email,
                "email_verified": email_verified,
            },
        )
        return None if row is None else User.from_mapping(row)

    async def mark_restricted(self, *, user_id: str) -> User:
        """Restrict a local user after signup orchestration failure."""
        row = await call_json_function("fn_users", 11, {"user_id": user_id})
        return User.from_mapping(row)

    async def complete_onboarding(
        self,
        *,
        user_id: str,
        display_name: str,
        account_mode: str,
    ) -> User | None:
        """Complete onboarding for a user in pending_profile_setup."""
        row = await call_json_function(
            "fn_users",
            13,
            {
                "user_id": user_id,
                "display_name": display_name,
                "account_mode": account_mode,
            },
        )
        return None if row is None else User.from_mapping(row)

    async def delete_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
        """Delete the local user row for a Keycloak subject."""
        row = await call_json_function("fn_users", 14, {"keycloak_sub": keycloak_sub})
        return None if row is None else User.from_mapping(row)
