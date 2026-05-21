"""Users domain repository ports."""

from __future__ import annotations

from typing import Protocol

from v1.models.user import BootstrapUserCommand, User


class UserRepository(Protocol):
    """Persistence operations required by users domain use cases."""

    async def bootstrap(self, command: BootstrapUserCommand) -> User:
        """Create or return a user for an identity subject."""
        ...

    async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
        """Return a user by external identity subject."""
        ...

    async def update_account_mode(self, *, keycloak_sub: str, account_mode: str) -> User:
        """Update app business account mode for an identity subject."""
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Return a user by normalized email."""
        ...

    async def create_pending_signup(
        self,
        *,
        email: str,
        display_name: str,
        account_mode: str,
        created_via: str,
    ) -> User:
        """Create or return a pending signup user."""
        ...

    async def link_keycloak_subject(
        self,
        *,
        user_id: str,
        keycloak_sub: str,
    ) -> User:
        """Link a pending local user to a Keycloak subject."""
        ...

    async def mark_verification_sent(self, *, user_id: str) -> User:
        """Record that a verification/setup email was sent."""
        ...

    async def activate_after_verified_signin(
        self,
        *,
        keycloak_sub: str,
        email: str,
        email_verified: bool,
    ) -> User | None:
        """Activate a pending user only after verified Keycloak signin."""
        ...

    async def mark_restricted(self, *, user_id: str) -> User:
        """Restrict a local user after an unrecoverable signup orchestration failure."""
        ...
