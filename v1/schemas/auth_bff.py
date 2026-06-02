"""BFF authentication request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator, model_validator

from domains.auth.password_policy import validate_signup_password


class SigninStartRequest(BaseModel):
    """Request to begin an OAuth2 authorization-code signin."""

    post_signin_redirect_uri: str | None = None


class SigninStartResponse(BaseModel):
    """Authorization URL and state returned to the browser."""

    authorization_url: str
    state: str
    expires_at: datetime


class ForgotPasswordRequest(BaseModel):
    """Public forgot-password request."""

    email: EmailStr


class SignupStartRequest(BaseModel):
    """Step 1 signup: email and password."""

    email: EmailStr
    password: SecretStr = Field(min_length=12, max_length=128)
    device_fingerprint: str = Field(min_length=8, max_length=256)
    captcha_token: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_password_policy(self) -> Self:
        validate_signup_password(
            password=self.password.get_secret_value(),
            email=str(self.email),
        )
        return self


class SignupCompleteRequest(BaseModel):
    """Step 2 signup: profile fields bound to a signup session token."""

    signup_token: str = Field(min_length=16, max_length=512)
    display_name: str = Field(min_length=1, max_length=120)
    account_mode: Literal["traveler", "messenger", "both"]

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return " ".join(value.strip().split())


class SignupRequest(BaseModel):
    """Deprecated single-step signup request."""

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    account_mode: Literal["traveler", "messenger", "both"]
    device_fingerprint: str = Field(min_length=8, max_length=256)
    captcha_token: str | None = Field(default=None, max_length=2048)
    post_signin_redirect_uri: str | None = None

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return " ".join(value.strip().split())


class SignupResendRequest(BaseModel):
    """Request to resend account verification/setup email."""

    email: EmailStr


class SocialSignupStartRequest(BaseModel):
    """Begin social signup with captured app account mode."""

    identity_provider: Literal["google", "apple"]
    account_mode: Literal["traveler", "messenger", "both"]
    device_fingerprint: str = Field(min_length=8, max_length=256)
    captcha_token: str | None = Field(default=None, max_length=2048)
    post_signin_redirect_uri: str | None = None


class GenericAuthResponse(BaseModel):
    """Generic auth response that avoids user enumeration."""

    status: str = "ok"


class SignupAcceptedResponse(BaseModel):
    """Generic signup response that avoids account enumeration."""

    status: str = "accepted"
    next_step: str = "check_email"


class SignupStartResponse(BaseModel):
    """Signup step 1 response."""

    status: str = "accepted"
    next_step: str = "complete_profile"
    signup_token: str | None = None
    expires_at: datetime | None = None


class SignupCompleteResponse(BaseModel):
    """Signup step 2 response."""

    status: str = "ok"
    next_step: str = "verify_email"


class LogoutResponse(BaseModel):
    """Logout response."""

    logout_url: str


class SessionResponse(BaseModel):
    """Public session metadata."""

    id: UUID
    status: str
    device_label: str | None = None
    last_seen_at: datetime
    created_at: datetime


class RevokeAllSessionsRequest(BaseModel):
    """Request to revoke all sessions."""

    keep_current: bool = Field(default=True)


class RevokeAllSessionsResponse(BaseModel):
    """Count of revoked sessions."""

    revoked_count: int
