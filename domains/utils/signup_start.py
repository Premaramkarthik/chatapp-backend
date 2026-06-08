"""Pure helpers for signup step 1 (start)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domains.auth.models import SignupStartResult
from domains.auth.security import hash_secret
from domains.auth.signup_security import normalize_email, request_hash
from domains.users.user import User

DUPLICATE_SIGNUP_STATUSES = frozenset({"active", "pending_profile_setup"})


@dataclass(frozen=True, slots=True)
class SignupStartContext:
    """Normalized signup-start inputs and idempotency hashes."""

    normalized_email: str
    email_hash: str
    payload_hash: str
    idempotency_hash: str


def build_signup_start_context(
    *,
    email: str,
    password: str,
    device_fingerprint: str,
    idempotency_key: str,
) -> SignupStartContext:
    """Build normalized email and idempotency hashes for signup start."""
    normalized_email = normalize_email(email)
    return SignupStartContext(
        normalized_email=normalized_email,
        email_hash=hash_secret(normalized_email),
        payload_hash=request_hash(
            {
                "email": normalized_email,
                "password_hash": hash_secret(password),
                "device_fingerprint": device_fingerprint,
            }
        ),
        idempotency_hash=hash_secret(idempotency_key),
    )


def signup_placeholder_name(email: str) -> str:
    """Return a temporary display name until profile completion."""
    return normalize_email(email).split("@", 1)[0]


def is_duplicate_signup_user(user: User | None) -> bool:
    """Return whether signup should respond generically for an existing account."""
    return user is not None and user.status in DUPLICATE_SIGNUP_STATUSES


def signup_start_result_from_mapping(data: dict) -> SignupStartResult:
    """Rebuild a signup start result from stored idempotency payload."""
    expires_at = data.get("expires_at")
    parsed_expires_at = datetime.fromisoformat(expires_at) if isinstance(expires_at, str) else None
    return SignupStartResult(
        status=str(data.get("status", "accepted")),
        next_step=str(data.get("next_step", "verify_email")),
        signup_token=data.get("signup_token"),
        expires_at=parsed_expires_at,
    )


def build_signup_start_idempotency_body(result: SignupStartResult) -> dict[str, str]:
    """Serialize signup start result for idempotency storage."""
    body: dict[str, str] = {
        "status": result.status,
        "next_step": result.next_step,
    }
    if result.signup_token is not None:
        body["signup_token"] = result.signup_token
    if result.expires_at is not None:
        body["expires_at"] = result.expires_at.isoformat()
    return body
