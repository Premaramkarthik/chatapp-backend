"""Unit tests for signup password policy."""

import pytest

from domains.auth.password_policy import PasswordPolicyError, validate_signup_password


def test_accepts_valid_password() -> None:
    validate_signup_password(password="SecurePassw0rd!12", email="user@example.com")


def test_rejects_password_matching_local_part() -> None:
    with pytest.raises(PasswordPolicyError) as exc_info:
        validate_signup_password(
            password="longusername",
            email="longusername@example.com",
        )
    assert exc_info.value.code == "password_matches_username"


@pytest.mark.parametrize(
    ("password", "code"),
    [
        ("", "password_required"),
        ("short1A!", "password_too_short"),
        ("a" * 129 + "A1!", "password_too_long"),
        ("user@example.com", "password_matches_email"),
        ("securepassw0rd!12", "password_missing_uppercase"),
        ("SECUREPASSW0RD!12", "password_missing_lowercase"),
        ("SecurePasswrd!!", "password_missing_digit"),
        ("SecurePassw0rd12", "password_missing_symbol"),
    ],
)
def test_rejects_invalid_passwords(password: str, code: str) -> None:
    with pytest.raises(PasswordPolicyError) as exc_info:
        validate_signup_password(password=password, email="user@example.com")
    assert exc_info.value.code == code
