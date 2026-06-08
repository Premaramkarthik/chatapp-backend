"""PostgreSQL users repository adapter."""

from __future__ import annotations

from domains.users.repository import UserRepository
from domains.users.user import BootstrapUserCommand, User
from infrastructure.database.connection import call_json_function


class PostgresUserRepository(UserRepository):
    """PostgreSQL adapter for users domain persistence."""

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
