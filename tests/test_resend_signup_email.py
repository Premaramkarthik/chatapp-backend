"""Resend signup verification email eligibility and cooldown tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from domains.auth.email_verification import VerificationEmail
from domains.auth.models import SignupResult
from domains.auth.service import (
    AuthService,
    _verification_cooldown_active,
    _verification_resend_eligibility,
)
from domains.auth.signup_security import SignupRateLimitResult
from domains.users.user import User
from v1.utils.base import IntegrationError


def _request() -> SimpleNamespace:
    return SimpleNamespace(headers={}, client=None, state=SimpleNamespace(request_id="req-1"))


async def _allow_resend_rate_limit(**_kwargs: object) -> SignupRateLimitResult:
    """Bypass Redis-backed resend rate limits in unit tests."""
    return SignupRateLimitResult(True)


def _pending_user(
    *,
    keycloak_sub: str | None = "kc-sub",
    status: str = "pending_verification",
    last_sent: datetime | None = None,
    send_count: int = 0,
    email_verified: bool = False,
) -> User:
    return User(
        id="user-id",
        keycloak_sub=keycloak_sub,
        email="user@example.com",
        display_name=None,
        status=status,
        email_verified=email_verified,
        last_verification_sent_at=last_sent,
        verification_send_count=send_count,
    )


class FakeSender:
    """Collect verification emails for assertions."""

    def __init__(self) -> None:
        self.messages: list[VerificationEmail] = []

    async def send(self, message: VerificationEmail) -> None:
        self.messages.append(message)


def test_verification_resend_eligibility_pending_without_keycloak_sub() -> None:
    """Pending users stay eligible even when Keycloak subject is not linked yet."""
    user = _pending_user(keycloak_sub=None)
    eligible, reason = _verification_resend_eligibility(user)
    assert eligible is True
    assert reason is None


def test_verification_resend_eligibility_rejects_active_user() -> None:
    """Verified or active accounts should not receive signup verification resends."""
    user = _pending_user(status="active", email_verified=True)
    eligible, reason = _verification_resend_eligibility(user)
    assert eligible is False
    assert reason == "user_not_eligible"


def test_verification_cooldown_active_within_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cooldown blocks resends inside the configured window."""
    monkeypatch.setattr(
        "domains.auth.service.settings.auth.signup_resend_cooldown_sec",
        60,
    )
    sent_at = datetime.now(UTC) - timedelta(seconds=30)
    assert _verification_cooldown_active(sent_at) is True


def test_verification_cooldown_inactive_after_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cooldown allows resends after the configured window."""
    monkeypatch.setattr(
        "domains.auth.service.settings.auth.signup_resend_cooldown_sec",
        60,
    )
    sent_at = datetime.now(UTC) - timedelta(seconds=90)
    assert _verification_cooldown_active(sent_at) is False


@pytest.mark.asyncio
async def test_resend_links_keycloak_sub_before_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "domains.auth.service.enforce_resend_rate_limit",
        _allow_resend_rate_limit,
    )
    """Resend should repair missing Keycloak linkage and deliver app verification email."""
    user = _pending_user(keycloak_sub=None)
    user_repository = AsyncMock()
    user_repository.get_by_email = AsyncMock(return_value=user)
    user_repository.link_keycloak_subject = AsyncMock(
        return_value=_pending_user(keycloak_sub="kc-sub"),
    )
    user_repository.mark_verification_sent = AsyncMock()

    keycloak = AsyncMock()
    keycloak.find_user_by_email = AsyncMock(return_value="kc-sub")
    keycloak.clear_required_actions = AsyncMock()

    sender = FakeSender()
    auth_repository = AsyncMock()
    auth_repository.write_outbox_event = AsyncMock()
    auth_repository.record_event = AsyncMock()

    service = AuthService(
        auth_repository=auth_repository,  # type: ignore[arg-type]
        user_repository=user_repository,  # type: ignore[arg-type]
        keycloak=keycloak,  # type: ignore[arg-type]
        email_verification=__import__(
            "domains.auth.email_verification",
            fromlist=["AppEmailVerificationIssuer"],
        ).AppEmailVerificationIssuer(
            auth_repository=auth_repository,
            sender=sender,  # type: ignore[arg-type]
        ),
    )

    result = await service.resend_signup_email(email="user@example.com", request=_request())

    assert isinstance(result, SignupResult)
    keycloak.find_user_by_email.assert_awaited_once_with("user@example.com")
    user_repository.link_keycloak_subject.assert_awaited_once()
    keycloak.clear_required_actions.assert_awaited_once_with(user_id="kc-sub")
    assert sender.messages[0].to_email == "user@example.com"
    user_repository.mark_verification_sent.assert_awaited_once_with(user_id="user-id")


@pytest.mark.asyncio
async def test_resend_still_sends_without_keycloak_sub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "domains.auth.service.enforce_resend_rate_limit",
        _allow_resend_rate_limit,
    )
    """App-owned verification should send even when Keycloak lookup fails."""
    user = _pending_user(keycloak_sub=None)
    user_repository = AsyncMock()
    user_repository.get_by_email = AsyncMock(return_value=user)
    user_repository.mark_verification_sent = AsyncMock()

    keycloak = AsyncMock()
    keycloak.find_user_by_email = AsyncMock(return_value=None)

    sender = FakeSender()
    auth_repository = AsyncMock()
    auth_repository.write_outbox_event = AsyncMock()
    auth_repository.record_event = AsyncMock()

    service = AuthService(
        auth_repository=auth_repository,  # type: ignore[arg-type]
        user_repository=user_repository,  # type: ignore[arg-type]
        keycloak=keycloak,  # type: ignore[arg-type]
        email_verification=__import__(
            "domains.auth.email_verification",
            fromlist=["AppEmailVerificationIssuer"],
        ).AppEmailVerificationIssuer(
            auth_repository=auth_repository,
            sender=sender,  # type: ignore[arg-type]
        ),
    )

    await service.resend_signup_email(email="user@example.com", request=_request())

    keycloak.clear_required_actions.assert_not_awaited()
    assert sender.messages[0].to_email == "user@example.com"


@pytest.mark.asyncio
async def test_resend_skips_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resend should no-op with cooldown_active when the last send is too recent."""
    monkeypatch.setattr(
        "domains.auth.service.enforce_resend_rate_limit",
        _allow_resend_rate_limit,
    )
    monkeypatch.setattr(
        "domains.auth.service.settings.auth.signup_resend_cooldown_sec",
        60,
    )
    user = _pending_user(last_sent=datetime.now(UTC))
    user_repository = AsyncMock()
    user_repository.get_by_email = AsyncMock(return_value=user)

    sender = FakeSender()
    auth_repository = AsyncMock()
    auth_repository.record_event = AsyncMock()
    service = AuthService(
        auth_repository=auth_repository,  # type: ignore[arg-type]
        user_repository=user_repository,  # type: ignore[arg-type]
        email_verification=__import__(
            "domains.auth.email_verification",
            fromlist=["AppEmailVerificationIssuer"],
        ).AppEmailVerificationIssuer(
            sender=sender
        ),  # type: ignore[arg-type]
    )

    result = await service.resend_signup_email(email="user@example.com", request=_request())

    assert isinstance(result, SignupResult)
    assert sender.messages == []


@pytest.mark.asyncio
async def test_resend_propagates_send_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eligible resend should surface SMTP delivery failures instead of silently accepting."""
    monkeypatch.setattr(
        "domains.auth.service.enforce_resend_rate_limit",
        _allow_resend_rate_limit,
    )
    user = _pending_user()
    user_repository = AsyncMock()
    user_repository.get_by_email = AsyncMock(return_value=user)

    email_verification = AsyncMock()
    email_verification.issue_and_send = AsyncMock(
        side_effect=IntegrationError("Verification email delivery failed"),
    )
    auth_repository = AsyncMock()
    auth_repository.record_event = AsyncMock()

    service = AuthService(
        auth_repository=auth_repository,  # type: ignore[arg-type]
        user_repository=user_repository,  # type: ignore[arg-type]
        email_verification=email_verification,  # type: ignore[arg-type]
    )

    with pytest.raises(IntegrationError):
        await service.resend_signup_email(email="user@example.com", request=_request())
