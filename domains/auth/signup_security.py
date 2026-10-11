"""Signup abuse protection, idempotency, and linking helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from core.config.settings import settings
from domains.auth.security import hash_secret
from infrastructure.redis.cache import auth_redis_cache
from v1.utils.base import AuthenticationError


class AccountLinkDecision(StrEnum):
    """Account linking policy decision."""

    ALLOW_PENDING_MATCH = "allow_pending_match"
    REJECT_ACTIVE_DUPLICATE = "reject_active_duplicate"
    REQUIRE_LINKING = "require_linking"


@dataclass(frozen=True, slots=True)
class SignupRateLimitResult:
    """Result for signup abuse checks."""

    allowed: bool
    reason: str | None = None


def normalize_email(email: str) -> str:
    """Normalize email for lookup and audit hashing."""
    return email.strip().lower()


def email_domain(email: str) -> str:
    """Return the normalized email domain."""
    return normalize_email(email).rsplit("@", 1)[-1]


def is_disposable_email(email: str) -> bool:
    """Return whether an email uses a blocked/disposable domain."""
    domain = email_domain(email)
    blocked = settings.auth.blocked_email_domains
    return domain in blocked or any(domain.endswith(f".{item}") for item in blocked)


def request_hash(payload: dict[str, Any]) -> str:
    """Create a stable hash for idempotency payload comparisons."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hash_secret(canonical)


async def enforce_signup_rate_limits(
    *,
    ip_address: str,
    device_fingerprint: str,
    email: str | None = None,
    social: bool = False,
) -> SignupRateLimitResult:
    """Apply Redis-backed signup velocity checks before Keycloak/SMTP work."""
    if social:
        allowed = await _hit_limit(
            f"signup:social:ip:{hash_secret(ip_address)}",
            settings.auth.signup_social_ip_limit,
            settings.auth.signup_social_ip_window_sec,
        )
        return SignupRateLimitResult(allowed, None if allowed else "social_ip_rate_limit")

    checks = [
        (
            f"signup:ip:{hash_secret(ip_address)}",
            settings.auth.signup_ip_limit,
            settings.auth.signup_ip_window_sec,
            "ip_rate_limit",
        ),
        (
            f"signup:device:{hash_secret(device_fingerprint)}",
            settings.auth.signup_device_limit,
            settings.auth.signup_device_window_sec,
            "device_rate_limit",
        ),
    ]
    if email:
        checks.append(
            (
                f"signup:domain:{email_domain(email)}",
                settings.auth.signup_domain_limit,
                settings.auth.signup_domain_window_sec,
                "domain_rate_limit",
            )
        )
    for key, limit, window, reason in checks:
        if not await _hit_limit(key, limit, window):
            return SignupRateLimitResult(False, reason)
    return SignupRateLimitResult(True)


async def enforce_resend_rate_limit(*, email: str) -> SignupRateLimitResult:
    """Apply resend email rate limit."""
    allowed = await _hit_limit(
        f"signup:resend:email:{hash_secret(normalize_email(email))}",
        settings.auth.signup_resend_email_limit,
        settings.auth.signup_resend_email_window_sec,
    )
    return SignupRateLimitResult(allowed, None if allowed else "resend_email_rate_limit")


def validate_captcha(captcha_token: str | None) -> None:
    """Validate presence of anti-automation token.

    Provider verification is intentionally an adapter seam. Local/dev defaults
    can keep enforcement disabled until Turnstile or hCaptcha credentials exist.
    """
    if settings.auth.captcha_required and not captcha_token:
        raise AuthenticationError("Signup verification failed")


def decide_account_linking(
    *,
    existing_status: str | None,
    existing_keycloak_sub: str | None,
    incoming_keycloak_sub: str,
    expected_identity_provider: str | None,
    incoming_identity_provider: str | None,
) -> AccountLinkDecision:
    """Apply conservative account linking policy."""
    if existing_keycloak_sub is not None and existing_keycloak_sub != incoming_keycloak_sub:
        return AccountLinkDecision.REQUIRE_LINKING
    if existing_status in {"active", "pending_profile_setup"}:
        if existing_keycloak_sub == incoming_keycloak_sub:
            return AccountLinkDecision.ALLOW_PENDING_MATCH
        return AccountLinkDecision.REJECT_ACTIVE_DUPLICATE
    if expected_identity_provider and incoming_identity_provider != expected_identity_provider:
        return AccountLinkDecision.REQUIRE_LINKING
    return AccountLinkDecision.ALLOW_PENDING_MATCH


async def _hit_limit(key: str, limit: int, window_sec: int) -> bool:
    count = await auth_redis_cache.increment(f"rate:{key}", ttl_sec=window_sec)
    return count <= limit
