"""Keycloak master-realm admin helpers for bootstrap and operational scripts."""

from __future__ import annotations

import asyncio
import time

import httpx

from core.config.settings import settings
from core.logging.logger import get_logger

logger = get_logger(__name__)


async def get_master_admin_token(
    *,
    base_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    timeout_seconds: float | None = None,
) -> str:
    """Return a master-realm admin access token via admin-cli password grant."""
    resolved_base = (base_url or settings.keycloak.internal_base).rstrip("/")
    resolved_user = username or settings.keycloak.bootstrap_admin
    resolved_password = password or settings.keycloak.bootstrap_admin_password_value
    timeout = timeout_seconds or settings.http.timeout_seconds
    token_url = f"{resolved_base}/realms/master/protocol/openid-connect/token"
    payload = {
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": resolved_user,
        "password": resolved_password,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(token_url, data=payload)
        response.raise_for_status()
        return str(response.json()["access_token"])


async def wait_for_keycloak(
    base_url: str | None = None,
    *,
    timeout_sec: float = 120.0,
    poll_interval_sec: float = 2.0,
) -> None:
    """Poll Keycloak until the master realm responds (works in dev without /health)."""
    resolved_base = (base_url or settings.keycloak.internal_base).rstrip("/")
    probe_url = f"{resolved_base}/realms/master"
    deadline = time.monotonic() + timeout_sec
    async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(probe_url)
                if response.status_code == 200:
                    logger.info("keycloak_ready base_url={}", resolved_base)
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(poll_interval_sec)
    raise TimeoutError(
        f"Keycloak did not become ready within {timeout_sec}s at {resolved_base}",
    )
