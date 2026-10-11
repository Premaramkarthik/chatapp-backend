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

# Built-in first broker login requires explicit ownership confirmation.
GOOGLE_BROKER_FLOW_ALIAS = "first broker login"


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
            # Forwarded to Google OAuth; always show account picker on broker sign-in.
            "prompt": "select_account",
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
    return {settings.auth.callback_url}


def _collect_web_origins() -> set[str]:
    """Collect allowed web origins for the public OIDC client."""
    origins = set(settings.auth.allowed_redirect_origins)
    for uri in _collect_web_redirect_uris():
        parsed = urlparse(uri)
        if parsed.scheme and parsed.netloc:
            origins.add(f"{parsed.scheme}://{parsed.netloc}")
    return origins


def _collect_post_logout_redirect_uris() -> set[str]:
    return {settings.auth.post_logout_redirect_url}


def _parse_post_logout_attribute(attributes: dict[str, Any] | None) -> set[str]:
    """Parse Keycloak client post.logout.redirect.uris attribute into a set."""
    raw = (attributes or {}).get("post.logout.redirect.uris", "")
    if not raw:
        return set()
    return {part for part in str(raw).split() if part}


def _format_post_logout_attribute(uris: set[str]) -> str:
    """Format post-logout redirect URIs for Keycloak client attributes."""
    return " ".join(sorted(uris))


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
    required_post_logout = _collect_post_logout_redirect_uris()
    attributes = dict(client_payload.get("attributes") or {})

    merged_redirects = sorted(required_redirects)
    merged_origins = sorted(required_origins)
    merged_post_logout = required_post_logout

    client_payload["publicClient"] = False
    client_payload["secret"] = keycloak.web_client_secret_value
    client_payload["directAccessGrantsEnabled"] = False
    attributes["pkce.code.challenge.method"] = "S256"
    client_payload["redirectUris"] = merged_redirects
    client_payload["webOrigins"] = merged_origins
    if merged_post_logout:
        attributes["post.logout.redirect.uris"] = _format_post_logout_attribute(merged_post_logout)
        client_payload["attributes"] = attributes
    update_response = await _request_with_admin_fallback(
        client=client,
        method="PUT",
        url=detail_url,
        json=client_payload,
    )
    update_response.raise_for_status()
    log_debug(
        logger,
        "Updated Keycloak web client redirect URIs, web origins, and post-logout URIs",
        client_id=keycloak.web_client_id,
        redirect_count=len(merged_redirects),
        origin_count=len(merged_origins),
        post_logout_count=len(merged_post_logout),
    )


async def ensure_keycloak_web_client() -> None:
    """Merge auth redirect, origin, and post-logout URIs into chatapp-web."""
    if not settings.keycloak.enabled:
        return

    async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
        await _ensure_web_client_redirect_uris(client)


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
        await _upsert_google_idp(client, idp_payload=idp_payload)

    log_debug(
        logger,
        "Google identity provider configured in Keycloak",
        realm=settings.keycloak.realm,
        alias=settings.keycloak.google_idp_alias,
    )
