"""Signup password validation aligned with Keycloak realm policy."""

from __future__ import annotations

import re

from core.config.settings import settings
from v1.utils.base import AppError

_UPPER = re.compile(r"[A-Z]")
_LOWER = re.compile(r"[a-z]")
_DIGIT = re.compile(r"[0-9]")
_SYMBOL = re.compile(r"[^A-Za-z0-9]")


class PasswordPolicyError(AppError):
    """Raised when a signup password fails local policy checks."""

    def __init__(self, code: str) -> None:
        super().__init__(message="Invalid password", code=code)


def validate_signup_password(*, password: str, email: str) -> None:
    """Validate signup password before Keycloak Admin API calls."""
    normalized = password.strip()
    if not normalized:
        raise PasswordPolicyError("password_required")

    min_length = settings.auth.signup_min_password_length
    max_length = settings.auth.signup_max_password_length
    if len(normalized) < min_length:
        raise PasswordPolicyError("password_too_short")
    if len(normalized) > max_length:
        raise PasswordPolicyError("password_too_long")

    normalized_email = email.strip().lower()
    if normalized.lower() == normalized_email:
        raise PasswordPolicyError("password_matches_email")

    local_part = normalized_email.split("@", 1)[0]
    if normalized.lower() == local_part.lower():
        raise PasswordPolicyError("password_matches_username")

    if not _UPPER.search(normalized):
        raise PasswordPolicyError("password_missing_uppercase")
    if not _LOWER.search(normalized):
        raise PasswordPolicyError("password_missing_lowercase")
    if not _DIGIT.search(normalized):
        raise PasswordPolicyError("password_missing_digit")
    if not _SYMBOL.search(normalized):
        raise PasswordPolicyError("password_missing_symbol")
