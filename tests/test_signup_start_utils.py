"""Unit tests for domains.utils signup helpers."""

from datetime import UTC, datetime

from domains.auth.models import SignupStartResult
from domains.users.user import User, UserStatus
from domains.utils.signup_start import (
    build_signup_start_context,
    build_signup_start_idempotency_body,
    is_duplicate_signup_user,
    signup_placeholder_name,
    signup_start_result_from_mapping,
)


def test_build_signup_start_context_normalizes_email_and_hashes() -> None:
    ctx = build_signup_start_context(
        email=" User@Example.COM ",
        password="SecurePassw0rd!12",
        device_fingerprint="device-12345678",
        idempotency_key="idem-key-1",
    )

    assert ctx.normalized_email == "user@example.com"
    assert ctx.email_hash
    assert ctx.payload_hash
    assert ctx.idempotency_hash
    assert ctx.email_hash != ctx.payload_hash


def test_signup_placeholder_name_uses_local_part() -> None:
    assert signup_placeholder_name("user@example.com") == "user"


def test_is_duplicate_signup_user_detects_active_accounts() -> None:
    user = User(
        id="user-id",
        email="user@example.com",
        status=UserStatus.ACTIVE.value,
        account_mode=None,
        display_name=None,
        keycloak_sub=None,
        email_verified=False,
        created_via="email",
        onboarding_completed_at=None,
        last_verification_sent_at=None,
        verification_send_count=0,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert is_duplicate_signup_user(user) is True
    assert is_duplicate_signup_user(None) is False


def test_signup_start_result_from_mapping_parses_expires_at() -> None:
    result = signup_start_result_from_mapping(
        {
            "status": "accepted",
            "next_step": "complete_profile",
            "signup_token": "token-abc",
            "expires_at": "2026-06-02T12:00:00+00:00",
        }
    )

    assert result.signup_token == "token-abc"
    assert result.expires_at == datetime(2026, 6, 2, 12, 0, tzinfo=UTC)


def test_build_signup_start_idempotency_body_omits_optional_fields() -> None:
    body = build_signup_start_idempotency_body(SignupStartResult())

    assert body == {"status": "accepted", "next_step": "complete_profile"}
