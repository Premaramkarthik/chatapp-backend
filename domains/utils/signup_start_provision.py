"""Keycloak and database provisioning for signup step 1."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.config.settings import settings
from core.logging.logger import get_logger
from domains.auth.keycloak_client import KeycloakAuthClient, keycloak_auth_client
from domains.auth.models import SignupStartResult
from domains.auth.security import expires_in, generate_token, hash_secret
from domains.utils.signup_start import signup_placeholder_name
from infrastructure.database.repositories.auth import PostgresAuthRepository
from infrastructure.database.repositories.users import PostgresUserRepository

if TYPE_CHECKING:
    from domains.users.user import User

logger = get_logger(__name__)


class SignupStartProvisioner:
    """Provision pending users and issue signup session tokens."""

    def __init__(
        self,
        *,
        user_repository: PostgresUserRepository | None = None,
        auth_repository: PostgresAuthRepository | None = None,
        keycloak: KeycloakAuthClient | None = None,
    ) -> None:
        self._user_repository = user_repository or PostgresUserRepository()
        self._auth_repository = auth_repository or PostgresAuthRepository()
        self._keycloak = keycloak or keycloak_auth_client

    async def get_or_create_pending_user(
        self,
        *,
        email: str,
        existing: User | None,
    ) -> User:
        """Return an existing pending user or create a new pending signup row."""
        if existing is not None:
            return existing
        return await self._user_repository.create_pending_signup(
            email=email,
            created_via="email",
        )

    async def provision(
        self,
        *,
        user: User,
        email: str,
        password: str,
        request_id: str | None = None,
    ) -> tuple[User, SignupStartResult, str]:
        """Create/link Keycloak user, send verification email, and issue signup session."""
        placeholder_name = signup_placeholder_name(email)

        keycloak_sub = user.keycloak_sub or await self._keycloak.create_user(
            email=email,
            display_name=placeholder_name,
            required_actions=[],
        )
        if user.keycloak_sub is None:
            logger.info(
                "keycloak_user_created request_id={} user_id={} keycloak_sub={}",
                request_id,
                user.id,
                keycloak_sub,
            )
            await self._keycloak.set_user_password(
                user_id=keycloak_sub,
                password=password,
                temporary=False,
            )
            logger.info(
                "keycloak_password_set request_id={} user_id={} keycloak_sub={}",
                request_id,
                user.id,
                keycloak_sub,
            )
            user = await self._user_repository.link_keycloak_subject(
                user_id=user.id,
                keycloak_sub=keycloak_sub,
            )

        await self._keycloak.clear_required_actions(user_id=keycloak_sub)

        await self._auth_repository.write_outbox_event(
            event_type="signup.created",
            aggregate_type="user",
            aggregate_id=user.id,
            payload={"created_via": "email"},
        )
        logger.info(
            "verification_email_requested request_id={} user_id={} keycloak_sub={}",
            request_id,
            user.id,
            keycloak_sub,
        )
        await self._keycloak.send_verification_email(user_id=keycloak_sub)
        await self._user_repository.mark_verification_sent(user_id=user.id)
        logger.info(
            "verification_email_sent request_id={} user_id={} keycloak_sub={}",
            request_id,
            user.id,
            keycloak_sub,
        )

        await self._auth_repository.write_outbox_event(
            event_type="signup.verification_email_sent",
            aggregate_type="user",
            aggregate_id=user.id,
            payload={},
        )

        signup_token = generate_token()
        expires_at = expires_in(settings.auth.signup_session_ttl_sec)
        await self._auth_repository.create_signup_session(
            user_id=user.id,
            token_hash=hash_secret(signup_token),
            expires_at=expires_at,
        )
        result = SignupStartResult(signup_token=signup_token, expires_at=expires_at)
        return user, result, keycloak_sub

    async def mark_provision_failure(self, *, user: User) -> None:
        """Restrict a user when signup orchestration fails."""
        await self._user_repository.mark_restricted(user_id=user.id)
        await self._auth_repository.write_outbox_event(
            event_type="account.restricted",
            aggregate_type="user",
            aggregate_id=user.id,
            payload={"reason": "signup_orchestration_failure"},
        )
