"""App-owned email verification tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from domains.auth.email_verification import AppEmailVerificationIssuer, VerificationEmail
from domains.auth.models import EmailVerificationToken
from domains.auth.security import hash_secret
from domains.auth.service import AuthService
from domains.users.user import User
from v1.utils.base import AuthenticationError


class FakeSender:
    """Collect verification emails for assertions."""

    def __init__(self) -> None:
        self.messages: list[VerificationEmail] = []

    async def send(self, message: VerificationEmail) -> None:
        self.messages.append(message)


class FakeTokenRepository:
    """In-memory verification token repository for service tests."""

    def __init__(self, token: EmailVerificationToken | None = None) -> None:
        self.token = token
        self.created_hash: str | None = None
        self.events: list[tuple[str, str | None]] = []

    async def create_email_verification_token(self, *, user_id: str, token_hash: str, expires_at):
        self.created_hash = token_hash
        self.token = EmailVerificationToken(
            id="token-id",
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        return self.token

    async def consume_email_verification_token(self, *, token_hash: str):
        if self.token is None:
            return None
        if self.token.token_hash != token_hash:
            return None
        if self.token.consumed_at is not None or self.token.expires_at <= datetime.now(UTC):
            return None
        self.token = EmailVerificationToken(
            id=self.token.id,
            user_id=self.token.user_id,
            token_hash=self.token.token_hash,
            expires_at=self.token.expires_at,
            consumed_at=datetime.now(UTC),
        )
        return self.token

    async def get_email_verification_token(self, *, token_hash: str):
        if self.token is None or self.token.token_hash != token_hash:
            return None
        return self.token

    async def write_outbox_event(self, *, event_type, aggregate_type, aggregate_id, payload):
        self.events.append((event_type, aggregate_id))

    async def record_event(self, **kwargs):
        self.events.append((kwargs["event_type"], kwargs.get("user_id")))


class FakeUserRepository:
    """Return and activate one pending user."""

    def __init__(self) -> None:
        self.user = User(
            id="user-id",
            keycloak_sub="kc-sub",
            email="user@example.com",
            display_name="User",
            status="pending_verification",
        )

    async def get_by_id(self, user_id: str):
        return self.user if user_id == self.user.id else None

    async def activate_after_verified_signin(
        self,
        *,
        keycloak_sub: str,
        email: str,
        email_verified: bool,
    ):
        if keycloak_sub != "kc-sub" or email != "user@example.com" or not email_verified:
            return None
        self.user = User(
            id="user-id",
            keycloak_sub="kc-sub",
            email="user@example.com",
            display_name="User",
            status="pending_profile_setup",
            email_verified=True,
        )
        return self.user


class FakeKeycloak:
    """Record Keycloak Admin API calls."""

    def __init__(self) -> None:
        self.verified_users: list[str] = []
        self.logged_out_users: list[str] = []

    async def mark_email_verified(self, *, user_id: str) -> None:
        self.verified_users.append(user_id)

    async def logout_user_sessions(self, *, user_id: str) -> None:
        self.logged_out_users.append(user_id)


class FakeSessionRepository:
    """Minimal auth repository for logout-all tests."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def revoke_all_sessions(self, *, user_id: str, keep_session_id: str | None = None):
        return []

    async def record_event(self, **kwargs):
        self.events.append(kwargs)


def _request():
    return SimpleNamespace(headers={}, client=None, state=SimpleNamespace(request_id="req-1"))


@pytest.mark.asyncio
async def test_issuer_generates_hashed_single_use_token_link() -> None:
    repo = FakeTokenRepository()
    sender = FakeSender()
    issuer = AppEmailVerificationIssuer(auth_repository=repo, sender=sender)
    user = User(
        id="user-id",
        keycloak_sub="kc-sub",
        email="user@example.com",
        display_name=None,
        status="pending_verification",
    )

    await issuer.issue_and_send(user=user)

    assert repo.created_hash is not None
    assert sender.messages[0].to_email == "user@example.com"
    token = parse_qs(urlparse(sender.messages[0].verify_link).query)["token"][0]
    assert repo.created_hash == hash_secret(token)
    assert repo.created_hash != token


@pytest.mark.asyncio
async def test_complete_email_verification_consumes_token_once() -> None:
    raw_token = "verify-token-value-123456"
    repo = FakeTokenRepository(
        EmailVerificationToken(
            id="token-id",
            user_id="user-id",
            token_hash=hash_secret(raw_token),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        ),
    )
    keycloak = FakeKeycloak()
    service = AuthService(
        auth_repository=repo,  # type: ignore[arg-type]
        user_repository=FakeUserRepository(),  # type: ignore[arg-type]
        keycloak=keycloak,  # type: ignore[arg-type]
        email_verification=AppEmailVerificationIssuer(auth_repository=repo),
    )

    activated = await service.complete_email_verification(token=raw_token, request=_request())

    assert activated.email_verified is True
    assert keycloak.verified_users == ["kc-sub"]
    with pytest.raises(AuthenticationError) as exc_info:
        await service.complete_email_verification(token=raw_token, request=_request())
    assert exc_info.value.code == "email_verification_invalid"


@pytest.mark.asyncio
async def test_complete_email_verification_rejects_expired_token() -> None:
    raw_token = "expired-token-value-123456"
    repo = FakeTokenRepository(
        EmailVerificationToken(
            id="token-id",
            user_id="user-id",
            token_hash=hash_secret(raw_token),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        ),
    )
    service = AuthService(
        auth_repository=repo,  # type: ignore[arg-type]
        user_repository=FakeUserRepository(),  # type: ignore[arg-type]
        keycloak=FakeKeycloak(),  # type: ignore[arg-type]
        email_verification=AppEmailVerificationIssuer(auth_repository=repo),
    )

    with pytest.raises(AuthenticationError) as exc_info:
        await service.complete_email_verification(token=raw_token, request=_request())

    assert exc_info.value.code == "email_verification_expired"


@pytest.mark.asyncio
async def test_revoke_all_sessions_logs_out_keycloak_sso_sessions() -> None:
    repo = FakeSessionRepository()
    keycloak = FakeKeycloak()
    service = AuthService(
        auth_repository=repo,  # type: ignore[arg-type]
        user_repository=FakeUserRepository(),  # type: ignore[arg-type]
        keycloak=keycloak,  # type: ignore[arg-type]
    )

    revoked = await service.revoke_all_sessions(
        user_id="user-id",
        keycloak_sub="kc-sub",
        keep_session_id=None,
        request=_request(),
    )

    assert revoked == 0
    assert keycloak.logged_out_users == ["kc-sub"]
