"""Apply Keycloak realm SMTP settings from application configuration."""

from __future__ import annotations

import httpx

from core.config.settings import settings
from core.logging.logger import get_logger
from infrastructure.keycloak.master_admin import get_master_admin_token

logger = get_logger(__name__)


def build_smtp_server_payload() -> dict[str, str] | None:
    """Build Keycloak smtpServer payload when required SMTP settings are present."""
    keycloak = settings.keycloak
    if not keycloak.smtp_host:
        return None

    missing: list[str] = []
    if not keycloak.smtp_from:
        missing.append("KEYCLOAK_SMTP_FROM")
    if not keycloak.smtp_user:
        missing.append("KEYCLOAK_SMTP_USER")
    if not keycloak.smtp_password_value:
        missing.append("KEYCLOAK_SMTP_PASSWORD")
    if missing:
        logger.warning(
            "keycloak_smtp_skip reason=incomplete_config missing={}",
            ",".join(missing),
        )
        return None

    return {
        "host": keycloak.smtp_host,
        "port": keycloak.smtp_port,
        "from": keycloak.smtp_from,
        "fromDisplayName": keycloak.smtp_from_display_name,
        "auth": "true",
        "user": keycloak.smtp_user,
        "password": keycloak.smtp_password_value,
        "starttls": keycloak.smtp_starttls,
        "ssl": keycloak.smtp_ssl,
    }


async def _client_credentials_token(
    *, base_url: str, realm: str, client_id: str, client_secret: str
) -> str:
    """Obtain a service-account access token for Keycloak Admin API calls."""
    token_url = f"{base_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
        response = await client.post(token_url, data=payload)
        response.raise_for_status()
        return str(response.json()["access_token"])


async def _apply_realm_smtp(
    *,
    client: httpx.AsyncClient,
    admin_realm_url: str,
    headers: dict[str, str],
    smtp_server: dict[str, str],
) -> None:
    """Merge smtpServer into the realm and persist via Admin REST API."""
    get_response = await client.get(admin_realm_url, headers=headers)
    get_response.raise_for_status()
    realm_payload = get_response.json()
    realm_payload["smtpServer"] = smtp_server
    put_response = await client.put(admin_realm_url, headers=headers, json=realm_payload)
    put_response.raise_for_status()


async def ensure_keycloak_smtp() -> None:
    """Apply SMTP settings to the configured realm when KEYCLOAK_SMTP_HOST is set."""
    if not settings.keycloak.enabled:
        return

    smtp_server = build_smtp_server_payload()
    if smtp_server is None:
        return

    keycloak = settings.keycloak
    admin_realm_url = keycloak.admin_realm_url
    token = await _client_credentials_token(
        base_url=keycloak.internal_base,
        realm=keycloak.realm,
        client_id=keycloak.admin_client_id,
        client_secret=keycloak.admin_client_secret_value,
    )
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
        try:
            await _apply_realm_smtp(
                client=client,
                admin_realm_url=admin_realm_url,
                headers=headers,
                smtp_server=smtp_server,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 403:
                raise
            bootstrap_token = await get_master_admin_token()
            bootstrap_headers = {"Authorization": f"Bearer {bootstrap_token}"}
            await _apply_realm_smtp(
                client=client,
                admin_realm_url=admin_realm_url,
                headers=bootstrap_headers,
                smtp_server=smtp_server,
            )

    logger.info(
        "keycloak_smtp_configured realm={} host={}",
        keycloak.realm,
        smtp_server["host"],
    )
