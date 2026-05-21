"""Authentication domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AuthSessionStatus(StrEnum):
    """Operational session states used for debugging and security actions."""

    ACTIVE = "ACTIVE"
    REFRESHING = "REFRESHING"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    COMPROMISED = "COMPROMISED"
    LOCKED = "LOCKED"


class AuthSecurityEventType(StrEnum):
    """Expected auth/security audit events."""

    SIGNIN_STARTED = "signin_started"
    SIGNIN_SUCCEEDED = "signin_succeeded"
    SIGNIN_FAILED = "signin_failed"
    LOGOUT_SUCCEEDED = "logout_succeeded"
    FORGOT_PASSWORD_REQUESTED = "forgot_password_requested"
    FORGOT_PASSWORD_EMAIL_SENT = "forgot_password_email_sent"
    SESSION_REVOKED = "session_revoked"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    REFRESH_FAILED = "refresh_failed"
    SIGNUP_REQUESTED = "signup_requested"
    SIGNUP_CREATED = "signup_created"
    SIGNUP_DUPLICATE = "signup_duplicate"
    SIGNUP_EMAIL_SENT = "signup_email_sent"
    SIGNUP_RESEND_REQUESTED = "signup_resend_requested"
    SIGNUP_ACTIVATED = "signup_activated"
    SIGNUP_DISPOSABLE_EMAIL_BLOCKED = "signup_disposable_email_blocked"
    ACCOUNT_LINKING_REQUIRED = "account_linking_required"


@dataclass(frozen=True, slots=True)
class TokenSet:
    """Token response returned by Keycloak."""

    access_token: str
    refresh_token: str | None
    id_token: str | None
    expires_at: datetime
    refresh_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class SigninState:
    """Stored one-time signin state."""

    id: str
    state_hash: str
    nonce_hash: str
    code_verifier_encrypted: str
    redirect_uri: str
    post_signin_redirect_uri: str
    expires_at: datetime
    consumed_at: datetime | None = None
    flow_type: str = "signin"
    account_mode: str | None = None
    identity_provider: str | None = None
    email_hash: str | None = None


@dataclass(frozen=True, slots=True)
class SignupResult:
    """Public generic signup result."""

    status: str = "accepted"
    next_step: str = "check_email"


@dataclass(frozen=True, slots=True)
class AuthSession:
    """Server-side BFF session snapshot."""

    id: str
    session_hash: str
    user_id: str
    keycloak_sub: str
    status: AuthSessionStatus
    access_token_encrypted: str
    refresh_token_encrypted: str | None
    id_token_encrypted: str | None
    access_expires_at: datetime
    refresh_expires_at: datetime | None
    idle_expires_at: datetime
    max_expires_at: datetime
    csrf_token_hash: str | None
    device_label: str | None
    ip_hash: str | None
    user_agent_hash: str | None
    last_seen_at: datetime
    created_at: datetime

    @property
    def is_usable(self) -> bool:
        """Return whether this session can authenticate a request."""
        return self.status == AuthSessionStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class SessionView:
    """Public session metadata returned to the current user."""

    id: str
    status: AuthSessionStatus
    device_label: str | None
    last_seen_at: datetime
    created_at: datetime
