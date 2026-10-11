"""Auth security helper tests."""

from domains.auth.anomaly import (
    AuthRiskLevel,
    classify_device_change,
    classify_refresh_failure,
)
from domains.auth.models import AuthSessionStatus
from domains.auth.security import (
    TokenCipher,
    create_pkce_challenge,
    create_pkce_verifier,
    hash_secret,
)
from domains.auth.service import transition_session_status
from domains.auth.signup_security import (
    AccountLinkDecision,
    decide_account_linking,
    email_domain,
    is_disposable_email,
    normalize_email,
    request_hash,
)
from domains.users.user import AccountMode


def test_pkce_challenge_is_stable_and_not_plaintext() -> None:
    verifier = create_pkce_verifier()
    challenge = create_pkce_challenge(verifier)

    assert challenge == create_pkce_challenge(verifier)
    assert challenge != verifier
    assert len(challenge) >= 43


def test_hash_secret_does_not_store_raw_value() -> None:
    value = "secret-session-token"

    assert hash_secret(value) != value
    assert hash_secret(value) == hash_secret(value)


def test_token_cipher_roundtrip() -> None:
    cipher = TokenCipher("unit-test-token-encryption-key")
    encrypted = cipher.encrypt("access-token")

    assert encrypted != "access-token"
    assert cipher.decrypt(encrypted) == "access-token"


def test_session_state_machine_allows_refresh_cycle() -> None:
    assert (
        transition_session_status(AuthSessionStatus.ACTIVE, AuthSessionStatus.REFRESHING)
        == AuthSessionStatus.REFRESHING
    )
    assert (
        transition_session_status(AuthSessionStatus.REFRESHING, AuthSessionStatus.ACTIVE)
        == AuthSessionStatus.ACTIVE
    )


def test_account_modes_are_business_state_not_roles() -> None:
    assert {mode.value for mode in AccountMode} == {"explorer", "connector"}


def test_anomaly_classification_thresholds() -> None:
    assert classify_refresh_failure(failure_count=2) is None
    assert classify_refresh_failure(failure_count=3).level == AuthRiskLevel.MEDIUM
    assert classify_refresh_failure(failure_count=10).level == AuthRiskLevel.HIGH
    assert classify_device_change(known_device=False).name == "suspicious_device_change"


def test_signup_email_helpers_normalize_and_block_disposable_domains() -> None:
    assert normalize_email(" USER@Example.COM ") == "user@example.com"
    assert email_domain("user@example.com") == "example.com"
    assert is_disposable_email("user@10minutemail.com") is True


def test_idempotency_request_hash_is_stable() -> None:
    first = request_hash({"email": "user@example.com", "account_mode": "explorer"})
    second = request_hash({"account_mode": "explorer", "email": "user@example.com"})

    assert first == second


def test_account_linking_rejects_active_duplicate_subject() -> None:
    assert (
        decide_account_linking(
            existing_status="active",
            existing_keycloak_sub="sub-a",
            incoming_keycloak_sub="sub-b",
            expected_identity_provider=None,
            incoming_identity_provider=None,
        )
        == AccountLinkDecision.REQUIRE_LINKING
    )


def test_pending_verification_does_not_allow_subject_reassignment():
    assert (
        decide_account_linking(
            existing_status="pending_verification",
            existing_keycloak_sub="original",
            incoming_keycloak_sub="attacker",
            expected_identity_provider=None,
            incoming_identity_provider=None,
        )
        == AccountLinkDecision.REQUIRE_LINKING
    )
