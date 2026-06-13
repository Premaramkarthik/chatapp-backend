"""Configure Keycloak Google identity provider and web client redirect URIs."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from core.config.settings import settings
from core.logging.logger import get_logger, log_debug, log_warning
from infrastructure.keycloak.master_admin import get_master_admin_token
from infrastructure.keycloak.smtp_config import _client_credentials_token

logger = get_logger(__name__)

# First-broker-login flow: new Google users are created; existing emails auto-link.
GOOGLE_BROKER_FLOW_ALIAS = "chatapp-google-auto-link"
_BROKER_FLOW_EXECUTIONS: tuple[tuple[str, str], ...] = (
    ("idp-create-user-if-unique", "ALTERNATIVE"),
    ("idp-auto-link", "ALTERNATIVE"),
)


def build_google_idp_payload() -> dict[str, Any] | None:
    """Build Keycloak Google IdP representation when credentials are configured."""
    keycloak = settings.keycloak
    if not keycloak.google_client_id:
        return None

    missing: list[str] = []
    if not keycloak.google_client_secret_value:
        missing.append("KEYCLOAK_GOOGLE_CLIENT_SECRET")
    if missing:
        log_warning(
            logger,
            "Skipping Google identity provider setup because configuration is incomplete",
            missing=",".join(missing),
        )
        return None

    hide_on_login = "true" if keycloak.google_idp_hide_on_login_page else "false"
    return {
        "alias": keycloak.google_idp_alias,
        "providerId": "google",
        "enabled": True,
        "trustEmail": True,
        "storeToken": False,
        "linkOnly": False,
        "firstBrokerLoginFlowAlias": GOOGLE_BROKER_FLOW_ALIAS,
        "config": {
            "clientId": keycloak.google_client_id,
            "clientSecret": keycloak.google_client_secret_value,
            "defaultScope": "openid profile email",
            "hideOnLoginPage": hide_on_login,
            "useJwksUrl": "true",
            "syncMode": "IMPORT",
        },
    }


def _uri_localhost_mirror(uri: str) -> str | None:
    """Return the same URI with localhost and 127.0.0.1 swapped, if applicable."""
    parsed = urlparse(uri)
    port_suffix = f":{parsed.port}" if parsed.port else ""
    if parsed.hostname == "localhost":
        return urlunparse(parsed._replace(netloc=f"127.0.0.1{port_suffix}"))
    if parsed.hostname == "127.0.0.1":
        return urlunparse(parsed._replace(netloc=f"localhost{port_suffix}"))
    return None


def _collect_web_redirect_uris() -> set[str]:
    """Collect BFF and frontend redirect URIs from auth settings."""
    uris = {
        settings.auth.callback_url,
        settings.auth.default_post_signin_redirect_url,
        settings.auth.email_verify_redirect_url,
    }
    expanded: set[str] = set()
    for uri in uris:
        expanded.add(uri)
        mirror = _uri_localhost_mirror(uri)
        if mirror:
            expanded.add(mirror)
    return expanded


def _collect_web_origins() -> set[str]:
    """Collect allowed web origins for the public OIDC client."""
    origins = set(settings.auth.allowed_redirect_origins)
    for uri in _collect_web_redirect_uris():
        parsed = urlparse(uri)
        if parsed.scheme and parsed.netloc:
            origins.add(f"{parsed.scheme}://{parsed.netloc}")
    return origins


async def _request_with_admin_fallback(
    *,
    client: httpx.AsyncClient,
    method: str,
    url: str,
    json: dict[str, Any] | None = None,
) -> httpx.Response:
    """Call Keycloak Admin API with service account, falling back to master admin on 403."""
    keycloak = settings.keycloak
    token = await _client_credentials_token(
        base_url=keycloak.internal_base,
        realm=keycloak.realm,
        client_id=keycloak.admin_client_id,
        client_secret=keycloak.admin_client_secret_value,
    )
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.request(method, url, headers=headers, json=json)
    if response.status_code != 403:
        return response
    bootstrap_token = await get_master_admin_token()
    bootstrap_headers = {"Authorization": f"Bearer {bootstrap_token}"}
    return await client.request(method, url, headers=bootstrap_headers, json=json)


async def _ensure_web_client_redirect_uris(client: httpx.AsyncClient) -> None:
    """Merge auth redirect URIs and web origins into chatapp-web when missing."""
    keycloak = settings.keycloak
    clients_url = f"{keycloak.admin_realm_url}/clients"
    list_response = await _request_with_admin_fallback(
        client=client,
        method="GET",
        url=clients_url,
        json=None,
    )
    list_response.raise_for_status()
    matches = [
        item for item in list_response.json() if item.get("clientId") == keycloak.web_client_id
    ]
    if not matches:
        log_warning(
            logger,
            "Skipping web client redirect URI update because client was not found",
            client_id=keycloak.web_client_id,
        )
        return

    client_uuid = matches[0]["id"]
    detail_url = f"{clients_url}/{client_uuid}"
    detail_response = await _request_with_admin_fallback(
        client=client,
        method="GET",
        url=detail_url,
        json=None,
    )
    detail_response.raise_for_status()
    client_payload = detail_response.json()

    required_redirects = _collect_web_redirect_uris()
    required_origins = _collect_web_origins()
    current_redirects = set(client_payload.get("redirectUris") or [])
    current_origins = set(client_payload.get("webOrigins") or [])

    merged_redirects = sorted(current_redirects | required_redirects)
    merged_origins = sorted(current_origins | required_origins)
    if merged_redirects == sorted(current_redirects) and merged_origins == sorted(current_origins):
        return

    client_payload["redirectUris"] = merged_redirects
    client_payload["webOrigins"] = merged_origins
    update_response = await _request_with_admin_fallback(
        client=client,
        method="PUT",
        url=detail_url,
        json=client_payload,
    )
    update_response.raise_for_status()
    log_debug(
        logger,
        "Updated Keycloak web client redirect URIs and web origins",
        client_id=keycloak.web_client_id,
        redirect_count=len(merged_redirects),
        origin_count=len(merged_origins),
    )


async def _flow_alias_exists(client: httpx.AsyncClient, *, flow_alias: str) -> bool:
    """Return True when an authentication flow alias already exists in the realm."""
    keycloak = settings.keycloak
    flows_url = f"{keycloak.admin_realm_url}/authentication/flows"
    response = await _request_with_admin_fallback(client=client, method="GET", url=flows_url)
    response.raise_for_status()
    return any(item.get("alias") == flow_alias for item in response.json())


async def _sync_broker_flow_requirements(client: httpx.AsyncClient) -> None:
    """Enable auto-link broker authenticators on the configured flow."""
    keycloak = settings.keycloak
    flows_url = f"{keycloak.admin_realm_url}/authentication/flows"
    list_response = await _request_with_admin_fallback(
        client=client,
        method="GET",
        url=f"{flows_url}/{GOOGLE_BROKER_FLOW_ALIAS}/executions",
    )
    list_response.raise_for_status()
    executions = list_response.json()
    providers = {item.get("providerId"): item for item in executions}
    update_url = f"{flows_url}/{GOOGLE_BROKER_FLOW_ALIAS}/executions"
    for provider, requirement in _BROKER_FLOW_EXECUTIONS:
        execution = providers.get(provider)
        if execution is None:
            log_warning(
                logger,
                "Broker flow execution is missing from Keycloak",
                flow=GOOGLE_BROKER_FLOW_ALIAS,
                provider=provider,
            )
            continue
        if execution.get("requirement") == requirement:
            continue
        execution_id = execution.get("id")
        if not execution_id:
            continue
        update_response = await _request_with_admin_fallback(
            client=client,
            method="PUT",
            url=update_url,
            json={"id": execution_id, "requirement": requirement},
        )
        update_response.raise_for_status()


async def _create_broker_auto_link_flow(client: httpx.AsyncClient) -> None:
    """Create the Google first-broker-login flow that auto-links by email."""
    keycloak = settings.keycloak
    flows_url = f"{keycloak.admin_realm_url}/authentication/flows"
    create_response = await _request_with_admin_fallback(
        client=client,
        method="POST",
        url=flows_url,
        json={
            "alias": GOOGLE_BROKER_FLOW_ALIAS,
            "description": "Auto-link Google accounts by email; create user when unique",
            "providerId": "basic-flow",
            "topLevel": True,
            "builtIn": False,
        },
    )
    create_response.raise_for_status()

    flow_executions_url = f"{flows_url}/{GOOGLE_BROKER_FLOW_ALIAS}/executions/execution"
    for provider, _requirement in _BROKER_FLOW_EXECUTIONS:
        add_response = await _request_with_admin_fallback(
            client=client,
            method="POST",
            url=flow_executions_url,
            json={"provider": provider},
        )
        add_response.raise_for_status()

    await _sync_broker_flow_requirements(client)


async def _ensure_google_broker_auto_link_flow(client: httpx.AsyncClient) -> None:
    """Ensure Keycloak uses auto-link first broker login for Google sign-in."""
    created = not await _flow_alias_exists(client, flow_alias=GOOGLE_BROKER_FLOW_ALIAS)
    if created:
        await _create_broker_auto_link_flow(client)
        log_debug(
            logger,
            "Configured Google broker auto-link flow in Keycloak",
            realm=settings.keycloak.realm,
            flow=GOOGLE_BROKER_FLOW_ALIAS,
        )
        return
    await _sync_broker_flow_requirements(client)


async def _upsert_google_idp(
    client: httpx.AsyncClient,
    *,
    idp_payload: dict[str, Any],
) -> None:
    """Create or update the Google identity provider in Keycloak."""
    keycloak = settings.keycloak
    alias = keycloak.google_idp_alias
    idp_url = f"{keycloak.admin_realm_url}/identity-provider/instances/{alias}"
    get_response = await _request_with_admin_fallback(client=client, method="GET", url=idp_url)
    if get_response.status_code == 404:
        create_url = f"{keycloak.admin_realm_url}/identity-provider/instances"
        create_response = await _request_with_admin_fallback(
            client=client,
            method="POST",
            url=create_url,
            json=idp_payload,
        )
        create_response.raise_for_status()
        return

    get_response.raise_for_status()
    existing = get_response.json()
    merged = {**existing, **idp_payload}
    merged["config"] = {**(existing.get("config") or {}), **idp_payload["config"]}
    update_response = await _request_with_admin_fallback(
        client=client,
        method="PUT",
        url=idp_url,
        json=merged,
    )
    update_response.raise_for_status()


async def ensure_keycloak_google_idp() -> None:
    """Configure Google IdP and web client redirects when Google OAuth env vars are set."""
    if not settings.keycloak.enabled:
        return

    idp_payload = build_google_idp_payload()
    if idp_payload is None:
        return

    async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
        await _ensure_web_client_redirect_uris(client)
        await _ensure_google_broker_auto_link_flow(client)
        await _upsert_google_idp(client, idp_payload=idp_payload)

    log_debug(
        logger,
        "Google identity provider configured in Keycloak",
        realm=settings.keycloak.realm,
        alias=settings.keycloak.google_idp_alias,
    )
