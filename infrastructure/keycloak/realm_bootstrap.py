"""Programmatic Keycloak realm bootstrap from the example realm JSON."""

from __future__ import annotations

import json

import httpx

from core.config.settings import REPO_ROOT, settings
from core.logging.logger import get_logger, log_debug
from infrastructure.keycloak.master_admin import get_master_admin_token, wait_for_keycloak
from v1.utils.base import ConfigurationError

logger = get_logger(__name__)

REALM_TEMPLATE_PATH = REPO_ROOT / "docker" / "keycloak" / "realm-chatapp.json.example"


def _load_realm_template() -> dict[str, object]:
    """Load the example realm JSON used for first-time bootstrap."""
    if not REALM_TEMPLATE_PATH.is_file():
        raise ConfigurationError(
            "Keycloak realm template is missing; expected "
            f"{REALM_TEMPLATE_PATH.relative_to(REPO_ROOT)}",
            context={"path": str(REALM_TEMPLATE_PATH)},
        )
    payload = json.loads(REALM_TEMPLATE_PATH.read_text(encoding="utf-8"))
    for client in payload["clients"]:
        if client["clientId"] == settings.keycloak.web_client_id:
            client["secret"] = settings.keycloak.web_client_secret_value
            client["redirectUris"] = [settings.auth.callback_url]
            client["attributes"][
                "post.logout.redirect.uris"
            ] = settings.auth.post_logout_redirect_url
        if client["clientId"] == settings.matrix.oidc_client_id:
            client["secret"] = settings.matrix.oidc_client_secret.get_secret_value()
            client["redirectUris"] = [
                settings.matrix.client_homeserver_url + "/_synapse/client/oidc/callback"
            ]
        if client["clientId"] == settings.keycloak.admin_client_id:
            client["secret"] = settings.keycloak.admin_client_secret_value
    return payload


async def ensure_keycloak_realm() -> None:
    """Create the configured realm when missing; no-op when already present."""
    if not settings.keycloak.enabled or not settings.keycloak.auto_bootstrap:
        return

    if (
        not settings.keycloak.bootstrap_admin
        or not settings.keycloak.bootstrap_admin_password_value
    ):
        raise ConfigurationError(
            "KEYCLOAK_BOOTSTRAP_ADMIN and KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD are "
            "required when KEYCLOAK_AUTO_BOOTSTRAP is enabled",
        )

    try:
        await wait_for_keycloak(settings.keycloak.internal_base)
    except TimeoutError as exc:
        raise ConfigurationError(
            "Keycloak is unreachable; start Keycloak before the API "
            "(see docs/keycloak-setup-guide.md)",
            context={"detail": str(exc)},
        ) from exc

    async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
        discovery = await client.get(settings.keycloak.well_known_url)
        if discovery.status_code == 200:
            log_debug(
                logger,
                "Skipping Keycloak realm bootstrap because realm already exists",
                realm=settings.keycloak.realm,
            )
            return
        if discovery.status_code != 404:
            discovery.raise_for_status()

    realm_payload = _load_realm_template()
    if str(realm_payload.get("realm", "")) != settings.keycloak.realm:
        raise ConfigurationError(
            "Realm template name does not match KEYCLOAK_REALM",
            context={
                "template_realm": realm_payload.get("realm"),
                "configured_realm": settings.keycloak.realm,
            },
        )

    try:
        token = await get_master_admin_token()
    except Exception as exc:
        raise ConfigurationError(
            "Keycloak master admin authentication failed; verify "
            "KEYCLOAK_BOOTSTRAP_ADMIN credentials",
            context={"detail": str(exc)},
        ) from exc

    create_url = f"{settings.keycloak.internal_base.rstrip('/')}/admin/realms"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
        response = await client.post(create_url, headers=headers, json=realm_payload)
        if response.status_code == 409:
            log_debug(
                logger,
                "Skipping Keycloak realm bootstrap because realm already exists",
                realm=settings.keycloak.realm,
                reason="conflict",
            )
            return
        if response.status_code >= 400:
            detail = response.text.strip()
            raise ConfigurationError(
                "Keycloak realm bootstrap failed",
                context={
                    "status_code": response.status_code,
                    "detail": detail,
                },
            )

    log_debug(
        logger,
        "Keycloak realm bootstrap completed",
        realm=settings.keycloak.realm,
        template=REALM_TEMPLATE_PATH.name,
    )
