"""App-owned password reset tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from domains.auth.models import PasswordResetToken
from domains.auth.password_reset import AppPasswordResetIssuer, PasswordResetEmail
from domains.auth.security import hash_secret
from domains.auth.service import AuthService
from domains.users.user import User
from v1.utils.base import AuthenticationError


def _fake_request() -> SimpleNamespace:
    return SimpleNamespace(headers={}, client=None, state=SimpleNamespace(request_id="req-1"))


class FakeSender:
    """Collect password reset emails for assertions."""

    def __init__(self) -> None:
        self.messages: list[PasswordResetEmail] = []

    async def send(self, message: PasswordResetEmail) -> None:
        self.messages.append(message)


class FakeTokenRepository:
    """In-memory password reset token repository for service tests."""

    def __init__(self, token: PasswordResetToken | None = None) -> None:
        self.token = token
        self.created_hash: str | None = None
        self.events: list[tuple[str, str | None]] = []

    async def create_password_reset_token(self, *, user_id: str, token_hash: str, expires_at):
        self.created_hash = token_hash
        self.token = PasswordResetToken(
            id="token-id",
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        return self.token

    async def consume_password_reset_token(self, *, token_hash: str):
        if self.token is None:
            return None
        if self.token.token_hash != token_hash:
            return None
        if self.token.consumed_at is not None or self.token.expires_at <= datetime.now(UTC):
            return None
        self.token = PasswordResetToken(
            id=self.token.id,
            user_id=self.token.user_id,
            token_hash=self.token.token_hash,
            expires_at=self.token.expires_at,
            consumed_at=datetime.now(UTC),
        )
        return self.token

    async def get_password_reset_token(self, *, token_hash: str):
        if self.token is None or self.token.token_hash != token_hash:
            return None
        return self.token

    async def record_event(self, **kwargs):
        self.events.append((kwargs["event_type"], kwargs.get("user_id")))


class FakeUserRepository:
    """Return one active user by email or id."""

    def __init__(self) -> None:
        self.user = User(
            id="user-id",
            keycloak_sub="kc-sub",
            email="user@example.com",
            display_name="User",
            status="active",
        )

    async def get_by_email(self, email: str):
        return self.user if email == "user@example.com" else None

    async def get_by_id(self, user_id: str):
        return self.user if user_id == self.user.id else None


class FakeKeycloak:
    """Record Keycloak Admin API calls."""

    def __init__(self) -> None:
        self.password_updates: list[tuple[str, str]] = []

    async def set_user_password(self, *, user_id: str, password: str, temporary: bool = False):
        self.password_updates.append((user_id, password))


@pytest.mark.asyncio
async def test_password_reset_issuer_sends_branded_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issuer stores token hash and emails an app-owned reset link."""
    monkeypatch.setattr(
        "domains.auth.password_reset.settings.auth.password_reset_redirect_url",
        "http://localhost:8080/reset-password",
    )
    sender = FakeSender()
    repo = FakeTokenRepository()
    issuer = AppPasswordResetIssuer(auth_repository=repo, sender=sender)
    user = User(
        id="user-id",
        keycloak_sub="kc-sub",
        email="user@example.com",
        display_name="User",
        status="active",
    )

    await issuer.issue_and_send(user=user)

    assert repo.created_hash is not None
    assert len(sender.messages) == 1
    parsed = urlparse(sender.messages[0].reset_link)
    assert parsed.path == "/reset-password"
    assert "token" in parse_qs(parsed.query)


@pytest.mark.asyncio
async def test_forgot_password_is_generic_when_user_missing() -> None:
    """Unknown emails still return without raising."""
    repo = FakeTokenRepository()
    user_repo = FakeUserRepository()
    user_repo.user = User(
        id="missing",
        keycloak_sub=None,
        email="other@example.com",
        display_name="Other",
        status="active",
    )
    service = AuthService(
        auth_repository=repo,
        user_repository=user_repo,
        password_reset=AppPasswordResetIssuer(auth_repository=repo, sender=FakeSender()),
    )
    await service.forgot_password(email="unknown@example.com", request=_fake_request())

    assert repo.created_hash is None


@pytest.mark.asyncio
async def test_complete_password_reset_updates_keycloak_password() -> None:
    """Valid token updates the Keycloak password and records an audit event."""
    raw_token = "a" * 32
    token_hash = hash_secret(raw_token)
    repo = FakeTokenRepository(
        PasswordResetToken(
            id="token-id",
            user_id="user-id",
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        ),
    )
    keycloak = FakeKeycloak()
    service = AuthService(
        auth_repository=repo,
        user_repository=FakeUserRepository(),
        keycloak=keycloak,
    )
    await service.complete_password_reset(
        token=raw_token,
        password="StrongPass1!",
        request=_fake_request(),
    )

    assert keycloak.password_updates == [("kc-sub", "StrongPass1!")]


@pytest.mark.asyncio
async def test_complete_password_reset_rejects_expired_token() -> None:
    """Expired tokens return a typed authentication error."""
    raw_token = "b" * 32
    token_hash = hash_secret(raw_token)
    repo = FakeTokenRepository(
        PasswordResetToken(
            id="token-id",
            user_id="user-id",
            token_hash=token_hash,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        ),
    )
    service = AuthService(
        auth_repository=repo,
        user_repository=FakeUserRepository(),
        keycloak=FakeKeycloak(),
    )
    with pytest.raises(AuthenticationError) as exc:
        await service.complete_password_reset(
            token=raw_token,
            password="StrongPass1!",
            request=_fake_request(),
        )

    assert exc.value.code == "password_reset_expired"
