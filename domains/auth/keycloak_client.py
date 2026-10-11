"""Async Keycloak OpenID Connect and Admin REST adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from core.config.settings import settings
from core.logging.logger import get_logger
from domains.auth.models import TokenSet
from infrastructure.keycloak.admin_client import KeycloakAdminClient, keycloak_admin_client
from v1.utils.base import AuthenticationError, KeycloakIntegrationError

logger = get_logger(__name__)


class KeycloakAuthClient:
    """Async adapter for Keycloak auth code, refresh, logout, and admin delegation."""

    def __init__(self, admin: KeycloakAdminClient | None = None) -> None:
        self._admin = admin or keycloak_admin_client

    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
        identity_provider: str | None = None,
        intent: str = "signin",
    ) -> str:
        """Build a browser authorization URL."""
        params = {
            "client_id": settings.keycloak.web_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if identity_provider:
            params["kc_idp_hint"] = identity_provider
            params["prompt"] = "select_account"
        endpoint = settings.keycloak.authorization_endpoint
        if intent == "signup":
            endpoint = endpoint.rsplit("/", 1)[0] + "/registrations"
        query = urlencode(params)
        return f"{endpoint}?{query}"

    async def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> TokenSet:
        """Exchange an auth code for tokens."""
        payload = {
            "grant_type": "authorization_code",
            "client_id": settings.keycloak.web_client_id,
            "client_secret": settings.keycloak.web_client_secret_value,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
        data = await self._post_token(payload, operation="exchange_code")
        return _token_set_from_response(data)

    async def refresh(self, *, refresh_token: str) -> TokenSet:
        """Refresh an access token using a BFF-held refresh token."""
        payload = {
            "grant_type": "refresh_token",
            "client_id": settings.keycloak.web_client_id,
            "client_secret": settings.keycloak.web_client_secret_value,
            "refresh_token": refresh_token,
        }
        data = await self._post_token(payload, operation="refresh_token")
        return _token_set_from_response(data)

    async def send_password_reset_email(self, *, email: str) -> bool:
        """Ask Keycloak to email UPDATE_PASSWORD to a matching user."""
        return await self._admin.send_password_reset_email(email=email)

    async def create_user(
        self,
        *,
        email: str,
        display_name: str,
        required_actions: list[str] | None = None,
    ) -> str:
        """Create a Keycloak user and return the Keycloak user ID/sub."""
        return await self._admin.create_user(
            email=email,
            display_name=display_name,
            required_actions=required_actions,
        )

    async def assign_default_client_roles(self, *, user_id: str) -> None:
        """Assign default chatapp-api capability roles to a Keycloak user."""
        await self._admin.assign_default_client_roles(user_id=user_id)

    async def send_account_setup_email(self, *, user_id: str) -> None:
        """Send a verify-only email (legacy alias)."""
        await self._admin.send_account_setup_email(user_id=user_id)

    async def find_user_by_email(self, email: str) -> str | None:
        """Return Keycloak user id for an exact email match."""
        return await self._admin.find_user_by_email(email)

    async def clear_required_actions(self, *, user_id: str) -> None:
        """Remove pending Keycloak required actions on a user."""
        await self._admin.clear_required_actions(user_id=user_id)

    async def set_user_password(
        self,
        *,
        user_id: str,
        password: str,
        temporary: bool = False,
    ) -> None:
        """Set a Keycloak user password via Admin API."""
        await self._admin.set_user_password(
            user_id=user_id,
            password=password,
            temporary=temporary,
        )

    async def send_verification_email(self, *, user_id: str) -> None:
        """Send a verification-only email."""
        await self._admin.send_verification_email(user_id=user_id)

    async def update_user_profile(
        self,
        *,
        user_id: str,
        display_name: str,
    ) -> None:
        """Update Keycloak profile fields for a user."""
        await self._admin.update_user_profile(user_id=user_id, display_name=display_name)

    async def mark_email_verified(self, *, user_id: str) -> None:
        """Mark a user's email as verified in Keycloak."""
        await self._admin.mark_email_verified(user_id=user_id)

    async def logout_user_sessions(self, *, user_id: str) -> None:
        """Revoke all Keycloak SSO sessions for a user."""
        await self._admin.logout_user_sessions(user_id=user_id)

    async def send_verify_email(self, *, user_id: str) -> None:
        """Send a pure email verification email."""
        await self._admin.send_verify_email(user_id=user_id)

    async def get_user_email_verified(self, *, user_id: str) -> bool:
        """Return whether Keycloak marks the user's email as verified."""
        return await self._admin.get_user_email_verified(user_id=user_id)

    async def delete_user(self, *, user_id: str) -> None:
        """Delete a Keycloak user account."""
        await self._admin.delete_user(user_id)

    async def _post_token(self, payload: dict[str, str], *, operation: str) -> dict[str, Any]:
        datetime.now(UTC)
        try:
            async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
                response = await client.post(settings.keycloak.token_endpoint, data=payload)
                response.raise_for_status()
                return dict(response.json())
        except httpx.HTTPStatusError as exc:
            raise _authentication_error_from_token_response(
                exc,
                grant_type=str(payload.get("grant_type", "")),
            ) from exc
        except httpx.HTTPError as exc:
            raise KeycloakIntegrationError("Keycloak token endpoint unavailable") from exc


def _authentication_error_from_token_response(
    exc: httpx.HTTPStatusError,
    *,
    grant_type: str,
) -> AuthenticationError:
    """Map Keycloak OAuth token errors to BFF authentication errors."""
    try:
        body = exc.response.json()
    except ValueError:
        body = {}
    error = str(body.get("error", ""))
    description = str(body.get("error_description", "")).lower()

    if grant_type == "password" and error == "invalid_grant":
        if "account is not fully set up" in description:
            return AuthenticationError(
                "Email verification is required before signin",
                code="email_verification_required",
            )
        if (
            "invalid user credentials" in description
            or "invalid username or password" in description
        ):
            return AuthenticationError("Invalid email or password")

    return AuthenticationError("Keycloak token request failed")


def _token_set_from_response(data: dict[str, Any]) -> TokenSet:
    access_token = str(data["access_token"])
    refresh_token = data.get("refresh_token")
    id_token = data.get("id_token")
    now = datetime.now(UTC)
    expires_at = _expiry_from_token(access_token) or now + timedelta(
        seconds=int(data.get("expires_in", 300))
    )
    refresh_expires_at = None
    if refresh_token:
        refresh_expires_at = _expiry_from_token(str(refresh_token)) or now + timedelta(
            seconds=int(data.get("refresh_expires_in", settings.auth.session_max_sec))
        )
    return TokenSet(
        access_token=access_token,
        refresh_token=None if refresh_token is None else str(refresh_token),
        id_token=None if id_token is None else str(id_token),
        expires_at=expires_at,
        refresh_expires_at=refresh_expires_at,
    )


def _expiry_from_token(token: str) -> datetime | None:
    try:
        claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
        exp = claims.get("exp")
    except Exception:
        return None
    if exp is None:
        return None
    return datetime.fromtimestamp(int(exp), tz=UTC)


keycloak_auth_client = KeycloakAuthClient()
