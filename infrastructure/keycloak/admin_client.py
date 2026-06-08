"""Keycloak Admin REST API client for user lifecycle management."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from core.config.settings import settings
from core.logging.domain_events import (
    KEYCLOAK_USER_CREATED,
    KEYCLOAK_USER_DELETED,
    KEYCLOAK_USER_UPDATED,
    PASSWORD_RESET_TRIGGERED,
    VERIFICATION_EMAIL_SENT,
    log_domain_event,
)
from core.logging.logger import get_logger
from core.observability.instrumentation import log_external_call
from v1.utils.base import KeycloakIntegrationError

logger = get_logger(__name__)


def _admin_log_path(url: str) -> str:
    """Return a realm-relative admin path suitable for structured logs."""
    prefix = settings.keycloak.admin_realm_url
    if url.startswith(prefix):
        return url[len(prefix) :]
    return url


def _log_admin_response(
    *,
    method: str,
    url: str,
    status_code: int | str,
    duration_ms: float,
    keycloak_user_id: str | None = None,
    error_type: str | None = None,
) -> None:
    """Emit structured logs for Keycloak Admin API calls."""
    fields = (
        "keycloak_admin_response method={} path={} status_code={} duration_ms={:.1f} "
        "keycloak_sub={}"
    )
    values: list[object] = [
        method,
        _admin_log_path(url),
        status_code,
        duration_ms,
        keycloak_user_id or "",
    ]
    if error_type:
        logger.warning(fields + " error_type={}", *values, error_type)
        return
    logger.info(fields, *values)


def _map_admin_error(exc: httpx.HTTPStatusError) -> KeycloakIntegrationError:
    """Map HTTP status codes to structured Keycloak integration errors."""
    status = exc.response.status_code
    if status in {401, 403}:
        return KeycloakIntegrationError(
            "Keycloak admin authorization failed",
            context={"status_code": status},
        )
    if status == 404:
        return KeycloakIntegrationError(
            "Keycloak resource not found",
            context={"status_code": status},
        )
    if status == 409:
        return KeycloakIntegrationError(
            "Keycloak resource conflict",
            context={"status_code": status},
        )
    return KeycloakIntegrationError(
        "Keycloak admin request failed",
        context={"status_code": status},
    )


class KeycloakAdminClient:
    """Async Keycloak Admin REST client with token caching and retries."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=settings.http.timeout_seconds)
        return self._client

    async def close(self) -> None:
        """Close the shared HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        token: str | None = None,
        keycloak_user_id: str | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute an Admin API request with retries and structured logging."""
        auth_token = token or await self.get_admin_token()
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {auth_token}"
        client = await self._http_client()
        last_exc: Exception | None = None
        start = datetime.now(UTC)

        for attempt in range(max(1, settings.http.retry_attempts)):
            try:
                async with log_external_call(operation):
                    from opentelemetry import trace

                    tracer = trace.get_tracer(__name__)
                    with tracer.start_as_current_span(f"keycloak.admin.{operation}"):
                        response = await client.request(method, url, headers=headers, **kwargs)
                if response.status_code >= 500 and attempt + 1 < settings.http.retry_attempts:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                response.raise_for_status()
                elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
                _log_admin_response(
                    method=method,
                    url=url,
                    status_code=response.status_code,
                    duration_ms=elapsed_ms,
                    keycloak_user_id=keycloak_user_id,
                )
                return response
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code >= 500 and attempt + 1 < settings.http.retry_attempts:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
                _log_admin_response(
                    method=method,
                    url=url,
                    status_code=exc.response.status_code,
                    duration_ms=elapsed_ms,
                    keycloak_user_id=keycloak_user_id,
                    error_type=type(exc).__name__,
                )
                raise _map_admin_error(exc) from exc
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt + 1 < settings.http.retry_attempts:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
                _log_admin_response(
                    method=method,
                    url=url,
                    status_code="error",
                    duration_ms=elapsed_ms,
                    keycloak_user_id=keycloak_user_id,
                    error_type=type(exc).__name__,
                )
                raise KeycloakIntegrationError("Keycloak admin request failed") from exc

        raise KeycloakIntegrationError("Keycloak admin request failed") from last_exc

    async def get_admin_token(self) -> str:
        """Return a cached service-account access token."""
        now = datetime.now(UTC)
        if (
            self._token is not None
            and self._token_expires_at is not None
            and self._token_expires_at > now + timedelta(seconds=30)
        ):
            return self._token

        async with self._lock:
            now = datetime.now(UTC)
            if (
                self._token is not None
                and self._token_expires_at is not None
                and self._token_expires_at > now + timedelta(seconds=30)
            ):
                return self._token

            payload = {
                "grant_type": "client_credentials",
                "client_id": settings.keycloak.admin_client_id,
                "client_secret": settings.keycloak.admin_client_secret_value,
            }
            client = await self._http_client()
            async with log_external_call("admin_token"):
                response = await client.post(settings.keycloak.token_endpoint, data=payload)
                response.raise_for_status()
                data = response.json()

            token = str(data["access_token"])
            expires_in = int(data.get("expires_in", 300))
            self._token = token
            self._token_expires_at = now + timedelta(seconds=max(60, expires_in - 30))
            return token

    async def find_user_by_email(self, email: str) -> str | None:
        """Return Keycloak user id for an exact email match."""
        token = await self.get_admin_token()
        url = f"{settings.keycloak.admin_realm_url}/users"
        response = await self._request(
            "GET",
            url,
            operation="find_user_by_email",
            token=token,
            params={"email": email, "exact": "true", "max": "2"},
        )
        users = response.json()
        if not users:
            return None
        return str(users[0]["id"])

    async def get_user(self, user_id: str) -> dict[str, Any]:
        """Fetch a Keycloak user representation."""
        token = await self.get_admin_token()
        url = f"{settings.keycloak.admin_realm_url}/users/{user_id}"
        response = await self._request(
            "GET",
            url,
            operation="get_user",
            token=token,
            keycloak_user_id=user_id,
        )
        return dict(response.json())

    async def create_user(
        self,
        *,
        email: str,
        display_name: str,
        required_actions: list[str] | None = None,
    ) -> str:
        """Create a Keycloak user and return the user id."""
        token = await self.get_admin_token()
        existing = await self.find_user_by_email(email)
        if existing:
            return existing

        payload = {
            "username": email,
            "email": email,
            "firstName": display_name,
            "enabled": True,
            "emailVerified": False,
            "requiredActions": required_actions or [],
        }
        url = f"{settings.keycloak.admin_realm_url}/users"
        client = await self._http_client()
        auth_token = token
        start = datetime.now(UTC)
        try:
            async with log_external_call("create_user"):
                from opentelemetry import trace

                tracer = trace.get_tracer(__name__)
                with tracer.start_as_current_span("keycloak.admin.create_user"):
                    response = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {auth_token}"},
                        json=payload,
                    )
            if response.status_code == 409:
                existing = await self.find_user_by_email(email)
                if existing:
                    return existing
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
            _log_admin_response(
                method="POST",
                url=url,
                status_code=exc.response.status_code,
                duration_ms=elapsed_ms,
                error_type=type(exc).__name__,
            )
            raise _map_admin_error(exc) from exc
        except httpx.HTTPError as exc:
            elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
            _log_admin_response(
                method="POST",
                url=url,
                status_code="error",
                duration_ms=elapsed_ms,
                error_type=type(exc).__name__,
            )
            raise KeycloakIntegrationError("Keycloak user creation failed") from exc

        elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
        _log_admin_response(
            method="POST",
            url=url,
            status_code=response.status_code,
            duration_ms=elapsed_ms,
        )

        location = response.headers.get("location", "")
        user_id = location.rstrip("/").rsplit("/", 1)[-1] if location else None
        if not user_id:
            user_id = await self.find_user_by_email(email)
        if not user_id:
            raise KeycloakIntegrationError("Keycloak user creation did not return a user id")

        await self.assign_client_roles(
            user_id=user_id,
            client_id=settings.keycloak.audience,
            role_names=settings.auth.default_signup_roles,
        )
        log_domain_event(KEYCLOAK_USER_CREATED, keycloak_sub=user_id)
        return user_id

    async def delete_user(self, user_id: str) -> None:
        """Delete a Keycloak user by id."""
        token = await self.get_admin_token()
        url = f"{settings.keycloak.admin_realm_url}/users/{user_id}"
        await self._request(
            "DELETE",
            url,
            operation="delete_user",
            token=token,
            keycloak_user_id=user_id,
        )
        log_domain_event(KEYCLOAK_USER_DELETED, keycloak_sub=user_id)

    async def update_user(self, *, user_id: str, fields: dict[str, Any]) -> None:
        """Update Keycloak user fields."""
        token = await self.get_admin_token()
        url = f"{settings.keycloak.admin_realm_url}/users/{user_id}"
        await self._request(
            "PUT",
            url,
            operation="update_user",
            token=token,
            keycloak_user_id=user_id,
            json=fields,
        )
        log_domain_event(KEYCLOAK_USER_UPDATED, keycloak_sub=user_id)

    async def update_user_profile(self, *, user_id: str, display_name: str) -> None:
        """Update Keycloak profile display name."""
        await self.update_user(user_id=user_id, fields={"firstName": display_name})

    async def clear_required_actions(self, *, user_id: str) -> None:
        """Remove pending Keycloak required actions on a user."""
        await self.update_user(user_id=user_id, fields={"requiredActions": []})

    async def set_user_password(
        self,
        *,
        user_id: str,
        password: str,
        temporary: bool = False,
    ) -> None:
        """Set a Keycloak user password via Admin API."""
        token = await self.get_admin_token()
        url = f"{settings.keycloak.admin_realm_url}/users/{user_id}/reset-password"
        await self._request(
            "PUT",
            url,
            operation="set_user_password",
            token=token,
            keycloak_user_id=user_id,
            json={"type": "password", "value": password, "temporary": temporary},
        )

    async def assign_client_roles(
        self,
        *,
        user_id: str,
        client_id: str,
        role_names: list[str],
    ) -> None:
        """Assign client roles to a user."""
        token = await self.get_admin_token()
        client_uuid = await self._client_uuid(client_id, token=token)
        roles = await self._client_role_representations(
            client_uuid=client_uuid,
            role_names=role_names,
            token=token,
        )
        if not roles:
            return
        url = (
            f"{settings.keycloak.admin_realm_url}/users/{user_id}"
            f"/role-mappings/clients/{client_uuid}"
        )
        await self._request(
            "POST",
            url,
            operation="assign_client_roles",
            token=token,
            keycloak_user_id=user_id,
            json=roles,
        )

    async def assign_default_client_roles(self, *, user_id: str) -> None:
        """Assign default signup capability roles."""
        await self.assign_client_roles(
            user_id=user_id,
            client_id=settings.keycloak.audience,
            role_names=settings.auth.default_signup_roles,
        )

    async def send_verify_email(self, *, user_id: str) -> None:
        """Send a verification email to the user."""
        token = await self.get_admin_token()
        url = f"{settings.keycloak.admin_realm_url}/users/{user_id}/send-verify-email"
        params: dict[str, str] = {"client_id": settings.keycloak.web_client_id}
        if settings.auth.email_verify_redirect_url:
            params["redirect_uri"] = settings.auth.email_verify_redirect_url
        await self._request(
            "PUT",
            url,
            operation="send_verify_email",
            token=token,
            keycloak_user_id=user_id,
            params=params,
        )
        log_domain_event(VERIFICATION_EMAIL_SENT, keycloak_sub=user_id)

    async def send_verification_email(self, *, user_id: str) -> None:
        """Alias for send_verify_email."""
        await self.send_verify_email(user_id=user_id)

    async def send_password_reset_email(self, *, email: str) -> bool:
        """Trigger UPDATE_PASSWORD action email. Returns False if user not found."""
        user_id = await self.find_user_by_email(email)
        if user_id is None:
            return False
        await self.execute_actions_email(user_id=user_id, actions=["UPDATE_PASSWORD"])
        log_domain_event(PASSWORD_RESET_TRIGGERED, keycloak_sub=user_id)
        return True

    async def send_account_setup_email(self, *, user_id: str) -> None:
        """Send a verify-only email (legacy name; no execute-actions wizard)."""
        await self.clear_required_actions(user_id=user_id)
        await self.send_verify_email(user_id=user_id)

    async def execute_actions_email(self, *, user_id: str, actions: list[str]) -> None:
        """Send execute-actions email for the given required actions."""
        token = await self.get_admin_token()
        url = f"{settings.keycloak.admin_realm_url}/users/{user_id}/execute-actions-email"
        params = {
            "client_id": settings.keycloak.web_client_id,
            "lifespan": str(settings.auth.reset_email_lifespan_sec),
        }
        await self._request(
            "PUT",
            url,
            operation="execute_actions_email",
            token=token,
            keycloak_user_id=user_id,
            params=params,
            json=actions,
        )

    async def get_user_email_verified(self, *, user_id: str) -> bool:
        """Return whether Keycloak marks the user's email as verified."""
        user = await self.get_user(user_id)
        return bool(user.get("emailVerified", False))

    async def client_exists(self, client_id: str) -> bool:
        """Return True when a realm client id exists."""
        token = await self.get_admin_token()
        try:
            await self._client_uuid(client_id, token=token)
        except KeycloakIntegrationError:
            return False
        return True

    async def client_role_exists(self, *, client_id: str, role_name: str) -> bool:
        """Return True when a client role exists."""
        token = await self.get_admin_token()
        client_uuid = await self._client_uuid(client_id, token=token)
        url = f"{settings.keycloak.admin_realm_url}/clients/{client_uuid}/roles/{role_name}"
        try:
            await self._request("GET", url, operation="get_client_role", token=token)
        except KeycloakIntegrationError:
            return False
        return True

    async def _client_uuid(self, client_id: str, *, token: str) -> str:
        url = f"{settings.keycloak.admin_realm_url}/clients"
        response = await self._request(
            "GET",
            url,
            operation="client_lookup",
            token=token,
            params={"clientId": client_id},
        )
        clients = response.json()
        if not clients:
            raise KeycloakIntegrationError(
                f"Keycloak client not found: {client_id}",
                context={"client_id": client_id},
            )
        return str(clients[0]["id"])

    async def _client_role_representations(
        self,
        *,
        client_uuid: str,
        role_names: list[str],
        token: str,
    ) -> list[dict[str, Any]]:
        roles: list[dict[str, Any]] = []
        for role_name in role_names:
            url = f"{settings.keycloak.admin_realm_url}/clients/{client_uuid}" f"/roles/{role_name}"
            response = await self._request(
                "GET",
                url,
                operation="client_role_lookup",
                token=token,
            )
            roles.append(response.json())
        return roles


keycloak_admin_client = KeycloakAdminClient()
