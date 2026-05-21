"""Async Keycloak OpenID Connect and Admin REST adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from v1.core.settings import settings
from v1.services.auth.models import TokenSet
from v1.utils.exception import AuthenticationError, KeycloakIntegrationError
from v1.utils.logger import get_logger
from v1.utils.metrics import metrics_registry

logger = get_logger(__name__)


class KeycloakAuthClient:
    """Async adapter for Keycloak auth code, refresh, logout, and reset email flows."""

    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
        identity_provider: str | None = None,
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
        query = urlencode(params)
        return f"{settings.keycloak.authorization_endpoint}?{query}"

    def logout_url(
        self,
        *,
        id_token_hint: str | None,
        post_logout_redirect_uri: str | None = None,
    ) -> str:
        """Build a browser RP-initiated logout URL."""
        params = {
            "client_id": settings.keycloak.web_client_id,
            "post_logout_redirect_uri": post_logout_redirect_uri
            or settings.auth.post_logout_redirect_url,
        }
        if id_token_hint:
            params["id_token_hint"] = id_token_hint
        return f"{settings.keycloak.logout_endpoint}?{urlencode(params)}"

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
        data = await self._post_token(payload, metric="auth_token_exchange_latency_seconds")
        return _token_set_from_response(data)

    async def refresh(self, *, refresh_token: str) -> TokenSet:
        """Refresh an access token using a BFF-held refresh token."""
        payload = {
            "grant_type": "refresh_token",
            "client_id": settings.keycloak.web_client_id,
            "client_secret": settings.keycloak.web_client_secret_value,
            "refresh_token": refresh_token,
        }
        data = await self._post_token(payload, metric="auth_refresh_latency_seconds")
        return _token_set_from_response(data)

    async def send_password_reset_email(self, *, email: str) -> bool:
        """Ask Keycloak to email UPDATE_PASSWORD to a matching user.

        The caller must always return a generic public response to prevent user
        enumeration. This return value is for audit/metrics only.
        """
        token = await self._admin_token()
        user_id = await self._find_user_id_by_email(email, token=token)
        if user_id is None:
            return False

        try:
            await self._execute_actions_email(
                user_id=user_id,
                token=token,
                actions=["UPDATE_PASSWORD"],
            )
        except httpx.HTTPError as exc:
            raise KeycloakIntegrationError("Keycloak password reset email failed") from exc
        return True

    async def create_user(
        self,
        *,
        email: str,
        display_name: str,
        required_actions: list[str],
    ) -> str:
        """Create a Keycloak user and return the Keycloak user ID/sub."""
        token = await self._admin_token()
        existing = await self._find_user_id_by_email(email, token=token)
        if existing:
            return existing

        payload = {
            "username": email,
            "email": email,
            "firstName": display_name,
            "enabled": True,
            "emailVerified": False,
            "requiredActions": required_actions,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.keycloak.admin_realm_url}/users",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                if response.status_code == 409:
                    existing = await self._find_user_id_by_email(email, token=token)
                    if existing:
                        return existing
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise KeycloakIntegrationError("Keycloak user creation failed") from exc

        location = response.headers.get("location", "")
        user_id = location.rstrip("/").rsplit("/", 1)[-1] if location else None
        if not user_id:
            user_id = await self._find_user_id_by_email(email, token=token)
        if not user_id:
            raise KeycloakIntegrationError("Keycloak user creation did not return a user id")
        await self.assign_default_client_roles(user_id=user_id)
        return user_id

    async def assign_default_client_roles(self, *, user_id: str) -> None:
        """Assign default chatapp-api capability roles to a Keycloak user."""
        token = await self._admin_token()
        client_uuid = await self._client_uuid(settings.keycloak.audience, token=token)
        roles = await self._client_role_representations(
            client_uuid=client_uuid,
            role_names=settings.auth.default_signup_roles,
            token=token,
        )
        if not roles:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.keycloak.admin_realm_url}/users/{user_id}"
                    f"/role-mappings/clients/{client_uuid}",
                    headers={"Authorization": f"Bearer {token}"},
                    json=roles,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise KeycloakIntegrationError("Keycloak role assignment failed") from exc

    async def send_account_setup_email(self, *, user_id: str) -> None:
        """Send initial setup email requiring verification and password setup."""
        token = await self._admin_token()
        await self._execute_actions_email(
            user_id=user_id,
            token=token,
            actions=["VERIFY_EMAIL", "UPDATE_PASSWORD"],
        )

    async def send_verify_email(self, *, user_id: str) -> None:
        """Send a pure email verification email."""
        token = await self._admin_token()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(
                    f"{settings.keycloak.admin_realm_url}/users/{user_id}/send-verify-email",
                    params={"client_id": settings.keycloak.web_client_id},
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise KeycloakIntegrationError("Keycloak verify email send failed") from exc

    async def _execute_actions_email(
        self,
        *,
        user_id: str,
        token: str,
        actions: list[str],
    ) -> None:
        params = {
            "client_id": settings.keycloak.web_client_id,
            "lifespan": str(settings.auth.reset_email_lifespan_sec),
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(
                    f"{settings.keycloak.admin_realm_url}/users/{user_id}/execute-actions-email",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    json=actions,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise KeycloakIntegrationError("Keycloak execute actions email failed") from exc

    async def _post_token(self, payload: dict[str, str], *, metric: str) -> dict[str, Any]:
        start = datetime.now(UTC)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(settings.keycloak.token_endpoint, data=payload)
                response.raise_for_status()
                return dict(response.json())
        except httpx.HTTPStatusError as exc:
            metrics_registry.increment(
                "auth_refresh_failure_total",
                reason=str(exc.response.status_code),
            )
            raise AuthenticationError("Keycloak token request failed") from exc
        except httpx.HTTPError as exc:
            metrics_registry.increment("auth_refresh_failure_total", reason=type(exc).__name__)
            raise KeycloakIntegrationError("Keycloak token endpoint unavailable") from exc
        finally:
            elapsed = (datetime.now(UTC) - start).total_seconds()
            metrics_registry.observe_total(metric, duration_seconds=elapsed)

    async def _admin_token(self) -> str:
        payload = {
            "grant_type": "client_credentials",
            "client_id": settings.keycloak.admin_client_id,
            "client_secret": settings.keycloak.admin_client_secret_value,
        }
        data = await self._post_token(payload, metric="auth_token_exchange_latency_seconds")
        return str(data["access_token"])

    async def _find_user_id_by_email(self, email: str, *, token: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{settings.keycloak.admin_realm_url}/users",
                    params={"email": email, "exact": "true", "max": "2"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise KeycloakIntegrationError("Keycloak user lookup failed") from exc

        users = response.json()
        if not users:
            return None
        return str(users[0]["id"])

    async def _client_uuid(self, client_id: str, *, token: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{settings.keycloak.admin_realm_url}/clients",
                    params={"clientId": client_id},
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise KeycloakIntegrationError("Keycloak client lookup failed") from exc
        clients = response.json()
        if not clients:
            raise KeycloakIntegrationError("Keycloak API client not found")
        return str(clients[0]["id"])

    async def _client_role_representations(
        self,
        *,
        client_uuid: str,
        role_names: list[str],
        token: str,
    ) -> list[dict[str, Any]]:
        roles: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for role_name in role_names:
                response = await client.get(
                    f"{settings.keycloak.admin_realm_url}/clients/{client_uuid}"
                    f"/roles/{role_name}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                roles.append(response.json())
        return roles


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
