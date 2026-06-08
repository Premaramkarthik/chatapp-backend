"""Keycloak startup validation for manually configured realms."""

from __future__ import annotations

import httpx

from core.config.settings import settings
from core.logging.logger import get_logger
from infrastructure.keycloak.admin_client import keycloak_admin_client
from v1.utils.base import ConfigurationError

logger = get_logger(__name__)


async def validate_keycloak_startup() -> None:
    """Verify Keycloak is reachable and preconfigured resources exist."""
    if not settings.keycloak.enabled:
        return

    try:
        async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
            response = await client.get(settings.keycloak.well_known_url)
            response.raise_for_status()
    except Exception as exc:
        raise ConfigurationError(
            "Keycloak OIDC discovery is unreachable; configure Keycloak manually "
            "(see docs/keycloak-setup-guide.md)",
            context={"detail": str(exc)},
        ) from exc

    try:
        await keycloak_admin_client.get_admin_token()
    except Exception as exc:
        raise ConfigurationError(
            "Keycloak admin service account authentication failed; verify "
            f"{settings.keycloak.admin_client_id} client credentials and roles",
            context={"detail": str(exc)},
        ) from exc

    required_clients = (
        settings.keycloak.web_client_id,
        settings.keycloak.audience,
    )
    for client_id in required_clients:
        if not await keycloak_admin_client.client_exists(client_id):
            raise ConfigurationError(
                f"Keycloak client '{client_id}' not found; create it in the Admin Console",
                context={"client_id": client_id},
            )

    for role_name in settings.auth.default_signup_roles:
        if not await keycloak_admin_client.client_role_exists(
            client_id=settings.keycloak.audience,
            role_name=role_name,
        ):
            raise ConfigurationError(
                f"Keycloak client role '{role_name}' missing on " f"{settings.keycloak.audience}",
                context={"role_name": role_name},
            )

    idp_alias = settings.keycloak.google_idp_alias
    if idp_alias:
        token = await keycloak_admin_client.get_admin_token()
        url = f"{settings.keycloak.admin_realm_url}/identity-provider/instances/{idp_alias}"
        try:
            async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code == 404:
                    logger.warning(
                        "keycloak_idp_missing alias={} configure in Admin Console if needed",
                        idp_alias,
                    )
        except Exception as exc:
            logger.warning(
                "keycloak_idp_check_failed alias={} error_type={}",
                idp_alias,
                type(exc).__name__,
            )

    logger.info(
        "keycloak_startup_validation_ok realm={} web_client={} api_client={}",
        settings.keycloak.realm,
        settings.keycloak.web_client_id,
        settings.keycloak.audience,
    )
