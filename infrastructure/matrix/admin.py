"""Synapse Admin API client via httpx."""

from __future__ import annotations

import time
from typing import Any

import httpx

from core.config.settings import settings
from core.logging.logger import get_logger, log_debug, log_warning
from core.observability.prometheus_metrics import (
    MATRIX_ADMIN_DURATION_SECONDS,
    MATRIX_ADMIN_REQUESTS_TOTAL,
)
from v1.utils.base import MatrixIntegrationError

logger = get_logger(__name__)


class SynapseAdminClient:
    """Minimal Synapse admin API wrapper for user lifecycle and login tokens."""

    def __init__(self, *, base_url: str | None = None, admin_token: str | None = None) -> None:
        self._base_url = (base_url or settings.matrix.homeserver_url).rstrip("/")
        self._admin_token = admin_token or settings.matrix.admin_token_value

    def _headers(self) -> dict[str, str]:
        if not self._admin_token:
            raise MatrixIntegrationError("MATRIX_ADMIN_TOKEN is not configured")
        return {"Authorization": f"Bearer {self._admin_token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an admin API request and return parsed JSON."""
        url = f"{self._base_url}{path}"
        started = time.perf_counter()
        operation = path.split("?")[0]
        try:
            async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
                response = await client.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json,
                )
                response.raise_for_status()
                MATRIX_ADMIN_REQUESTS_TOTAL.labels(operation=operation, status="success").inc()
                if not response.content:
                    return {}
                payload = response.json()
                return payload if isinstance(payload, dict) else {"data": payload}
        except httpx.HTTPStatusError as exc:
            MATRIX_ADMIN_REQUESTS_TOTAL.labels(
                operation=operation,
                status=str(exc.response.status_code),
            ).inc()
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
        except Exception as exc:
            MATRIX_ADMIN_REQUESTS_TOTAL.labels(operation=operation, status="error").inc()
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
            MATRIX_ADMIN_DURATION_SECONDS.labels(operation=operation).observe(duration)
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
        password: str,
        displayname: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a Matrix user account."""
        body: dict[str, Any] = {
            "password": password,
            "admin": False,
            "deactivated": False,
        }
        if displayname:
            body["displayname"] = displayname
        return await self._request("PUT", f"/_synapse/admin/v2/users/{mxid}", json=body)

    async def create_login_token(
        self,
        *,
        mxid: str,
        valid_until_ms: int | None = None,
    ) -> dict[str, Any]:
        """Issue a short-lived access token for matrix-js-sdk login."""
        body: dict[str, Any] = {}
        if valid_until_ms is not None:
            body["valid_until_ms"] = valid_until_ms
        return await self._request(
            "POST",
            f"/_synapse/admin/v1/users/{mxid}/login",
            json=body or None,
        )

    async def deactivate_user(self, *, mxid: str) -> dict[str, Any]:
        """Deactivate a Matrix user account."""
        return await self._request(
            "POST",
            f"/_synapse/admin/v1/deactivate/{mxid}",
            json={"erase": False},
        )

    async def search_users(self, *, search_term: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search users via Synapse admin user directory."""
        payload = await self._request(
            "GET",
            f"/_synapse/admin/v2/users?search_term={search_term}&limit={limit}",
        )
        users = payload.get("users")
        return users if isinstance(users, list) else []


synapse_admin_client = SynapseAdminClient()
