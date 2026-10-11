"""Synapse Admin API client via httpx."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote

import httpx

from core.config.settings import settings
from core.logging.logger import get_logger, log_debug, log_warning
from v1.utils.base import MatrixIntegrationError

logger = get_logger(__name__)


class SynapseAdminClient:
    """Minimal Synapse admin API wrapper for user lifecycle and login tokens."""

    def __init__(self, *, base_url: str | None = None, admin_token: str | None = None) -> None:
        self._base_url = (base_url or settings.matrix.homeserver_url).rstrip("/")
        override = admin_token if admin_token is not None else settings.matrix.admin_token_value
        self._static_token = override or None
        self._access_token: str | None = None
        self._login_lock = asyncio.Lock()

    @property
    def service_admin_mxid(self) -> str:
        """Return configured service admin MXID."""
        return settings.matrix.service_admin_mxid

    async def login(self) -> str:
        """Obtain and cache a Synapse admin access token."""
        if self._static_token:
            self._access_token = self._static_token
            return self._static_token
        async with self._login_lock:
            if self._access_token:
                return self._access_token
            return await self._login_unlocked()

    async def get_token(self) -> str:
        """Return cached admin token, logging in when needed."""
        if self._static_token:
            return self._static_token
        if self._access_token:
            return self._access_token
        return await self.login()

    async def retry_login(self) -> str:
        """Force a fresh service-admin login after auth failures."""
        if self._static_token:
            return self._static_token
        async with self._login_lock:
            self._access_token = None
            return await self._login_unlocked()

    async def verify_admin_access(self) -> None:
        """Confirm the current token can reach the Synapse Admin API."""
        mxid = self.service_admin_mxid
        await self._request("GET", f"/_synapse/admin/v2/users/{quote(mxid, safe='')}")

    async def _login_unlocked(self) -> str:
        """Login without acquiring the lock (caller must hold it)."""
        url = f"{self._base_url}/_matrix/client/v3/login"
        body = {
            "type": "m.login.password",
            "identifier": {
                "type": "m.id.user",
                "user": settings.matrix.service_admin_user,
            },
            "password": settings.matrix.service_admin_password_value,
        }
        return await self._login_post(url, body)

    async def _login_post(
        self,
        url: str,
        body: dict[str, Any],
        *,
        _rate_limit_retry: bool = True,
    ) -> str:
        """POST login and return access_token, with one short 429 backoff."""
        try:
            async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
                response = await client.post(url, json=body)
                if response.status_code == 429 and _rate_limit_retry and not self._static_token:
                    retry_after_ms = 0
                    try:
                        payload = response.json()
                        retry_after_ms = int(payload.get("retry_after_ms") or 0)
                    except Exception:
                        retry_after_ms = 0
                    # ponytail: one short wait for dev reload bursts; long blocks fail fast
                    if 0 < retry_after_ms <= 15_000:
                        await asyncio.sleep(retry_after_ms / 1000)
                        return await self._login_post(url, body, _rate_limit_retry=False)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            context: dict[str, Any] = {"status_code": exc.response.status_code}
            if exc.response.status_code == 429:
                context["hint"] = (
                    "Synapse login rate limit exceeded; wait and restart, "
                    "or restart synapse after homeserver rc_login changes"
                )
            raise MatrixIntegrationError(
                "Matrix service admin login failed",
                context=context,
            ) from exc
        except Exception as exc:
            raise MatrixIntegrationError(
                "Matrix service admin login failed",
                context={"detail": str(exc)},
            ) from exc

        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise MatrixIntegrationError(
                "Matrix service admin login returned no access_token",
            )
        self._access_token = token
        return token

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        _retry: bool = True,
    ) -> dict[str, Any]:
        """Execute an admin API request and return parsed JSON."""
        url = f"{self._base_url}{path}"
        started = time.perf_counter()
        path.split("?")[0]
        token = await self.get_token()
        try:
            async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
                response = await client.request(
                    method,
                    url,
                    headers=self._auth_headers(token),
                    json=json,
                )
                if response.status_code == 401 and _retry and not self._static_token:
                    await self.retry_login()
                    return await self._request(method, path, json=json, _retry=False)
                response.raise_for_status()
                if not response.content:
                    return {}
                payload = response.json()
                return payload if isinstance(payload, dict) else {"data": payload}
        except httpx.HTTPStatusError as exc:
            log_warning(
                logger,
                "Synapse admin request failed",
                matrix_category="admin",
                method=method,
                path=path,
                status_code=exc.response.status_code,
            )
            raise MatrixIntegrationError(
                "Synapse admin request failed",
                context={"path": path, "status_code": exc.response.status_code},
            ) from exc
        except MatrixIntegrationError:
            raise
        except Exception as exc:
            log_warning(
                logger,
                "Synapse admin request error",
                matrix_category="admin",
                method=method,
                path=path,
                error_type=type(exc).__name__,
            )
            raise MatrixIntegrationError(
                "Synapse admin request failed",
                context={"path": path},
            ) from exc
        finally:
            duration = time.perf_counter() - started
            log_debug(
                logger,
                "Synapse admin request completed",
                matrix_category="admin",
                method=method,
                path=path,
                duration_ms=f"{duration * 1000:.1f}",
            )

    async def create_or_update_user(
        self,
        *,
        mxid: str,
        password: str | None = None,
        subject: str | None = None,
        displayname: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a Matrix user account."""
        body: dict[str, Any] = {
            "admin": False,
            "deactivated": False,
        }
        if password is not None:
            body["password"] = password
        if subject:
            existing = None
            try:
                existing = await self._request(
                    "GET", f"/_synapse/admin/v2/users/{quote(mxid, safe='')}"
                )
            except MatrixIntegrationError as exc:
                if (exc.context or {}).get("status_code") != 404:
                    raise
            links = (existing or {}).get("external_ids", [])
            own = [
                link
                for link in links
                if link.get("auth_provider") == settings.matrix.oidc_provider_id
            ]
            if own and any(link.get("external_id") != subject for link in own):
                raise MatrixIntegrationError("Matrix account linking required")
            body["external_ids"] = [
                link
                for link in links
                if link.get("auth_provider") != settings.matrix.oidc_provider_id
            ] + [{"auth_provider": settings.matrix.oidc_provider_id, "external_id": subject}]
        if displayname:
            body["displayname"] = displayname
        return await self._request(
            "PUT", f"/_synapse/admin/v2/users/{quote(mxid, safe='')}", json=body
        )

    async def create_login_token(
        self,
        *,
        mxid: str,
        valid_until_ms: int | None = None,
    ) -> dict[str, Any]:
        """Issue a bounded internal provisioning token; never expose it to browsers."""
        body: dict[str, Any] = {}
        if valid_until_ms is not None:
            body["valid_until_ms"] = valid_until_ms
        return await self._request(
            "POST",
            f"/_synapse/admin/v1/users/{quote(mxid, safe='')}/login",
            json=body or None,
        )

    async def deactivate_user(self, *, mxid: str) -> dict[str, Any]:
        """Deactivate a Matrix user account."""
        return await self._request(
            "POST",
            f"/_synapse/admin/v1/deactivate/{quote(mxid, safe='')}",
            json={"erase": False},
        )

    async def delete_device(self, *, mxid: str, device_id: str) -> None:
        """Invalidate the real device and its tokens; retrying missing devices succeeds."""
        try:
            await self._request(
                "DELETE",
                f"/_synapse/admin/v2/users/{quote(mxid, safe='')}/devices/"
                f"{quote(device_id, safe='')}",
                json={},
            )
        except MatrixIntegrationError as exc:
            if (exc.context or {}).get("status_code") != 404:
                raise

    async def search_users(self, *, search_term: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search users via Synapse admin user directory."""
        payload = await self._request(
            "GET",
            f"/_synapse/admin/v2/users?search_term={quote(search_term, safe='')}&limit={limit}",
        )
        users = payload.get("users")
        return users if isinstance(users, list) else []


synapse_admin_client = SynapseAdminClient()
