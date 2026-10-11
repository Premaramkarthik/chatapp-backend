"""Security helpers for BFF authentication flows."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from core.config.settings import settings
from v1.utils.base import AuthenticationError, ConfigurationError


def now_utc() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(UTC)


def expires_in(seconds: int) -> datetime:
    """Return a UTC expiry timestamp."""
    return now_utc() + timedelta(seconds=seconds)


def generate_token(bytes_length: int = 32) -> str:
    """Generate a URL-safe random token."""
    return secrets.token_urlsafe(bytes_length)


def hash_secret(value: str) -> str:
    """Hash a secret for lookup or audit without storing the raw value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_optional(value: str | None) -> str | None:
    """Hash a nullable value."""
    return None if value is None else hash_secret(value)


def constant_time_equal(first: str, second: str) -> bool:
    """Compare two strings without timing leaks."""
    return hmac.compare_digest(first, second)


def create_pkce_verifier() -> str:
    """Create a high-entropy PKCE verifier."""
    return generate_token(64)


def create_pkce_challenge(verifier: str) -> str:
    """Create a PKCE S256 challenge from a verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class TokenCipher:
    """Encrypt OAuth tokens before persistence."""

    def __init__(self, key_material: str | None = None) -> None:
        material = key_material or settings.auth.token_encryption_key_value
        self._fernet = Fernet(_normalize_fernet_key(material))

    def encrypt(self, value: str | None) -> str | None:
        """Encrypt a nullable token value."""
        if value is None:
            return None
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        """Decrypt a nullable token value."""
        if value is None:
            return None
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise AuthenticationError("Stored authentication token could not be decrypted") from exc


def validate_post_signin_redirect(uri: str | None) -> str:
    """Return a safe post-signin redirect URI from allowlisted origins."""
    candidate = uri or settings.auth.default_post_signin_redirect_url
    parsed = urlparse(candidate)
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.fragment:
        raise AuthenticationError("Invalid redirect URI")

    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in settings.auth.allowed_redirect_origins:
        raise AuthenticationError("Redirect URI origin is not allowed")
    if candidate != settings.auth.default_post_signin_redirect_url:
        raise AuthenticationError("Redirect URI path is not allowed")
    if settings.app.environment.lower() in {"production", "prod"} and parsed.scheme != "https":
        raise AuthenticationError("HTTPS redirect required")
    return candidate


def _normalize_fernet_key(material: str) -> bytes:
    """Accept a Fernet key or derive one from passphrase-like env material."""
    if not material:
        raise ConfigurationError("AUTH_TOKEN_ENCRYPTION_KEY is required")

    raw = material.encode("utf-8")
    try:
        Fernet(raw)
        return raw
    except Exception:
        digest = hashlib.sha256(raw).digest()
        return base64.urlsafe_b64encode(digest)
