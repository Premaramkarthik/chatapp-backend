"""Session checks and scoped logout using the standard Keycloak Admin REST API."""

from urllib.parse import quote, urlencode

import httpx
from fastapi import HTTPException

from core.config.settings import settings
from infrastructure.keycloak.admin_client import keycloak_admin_client
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.base import AuthenticationError, KeycloakIntegrationError


class SessionControl:
    async def request(self, method: str, path: str, *, params=None):
        try:
            token = await keycloak_admin_client.get_admin_token()
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.request(
                    method,
                    settings.keycloak.admin_realm_url + path,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.json() if response.content else None
        except (httpx.HTTPError, ValueError, KeycloakIntegrationError) as exc:
            raise HTTPException(503, detail={"code": "auth_provider_unavailable"}) from exc

    async def sessions(self, subject: str) -> list[dict]:
        subject = quote(subject, safe="")
        online = await self.request("GET", f"/users/{subject}/sessions") or []
        clients = (
            await self.request(
                "GET", "/clients", params={"clientId": settings.keycloak.web_client_id}
            )
            or []
        )
        if len(clients) != 1:
            raise HTTPException(503, detail={"code": "auth_provider_unavailable"})
        offline = (
            await self.request(
                "GET", f"/users/{subject}/offline-sessions/{quote(clients[0]['id'], safe='')}"
            )
            or []
        )
        return [dict(row, offline=False) for row in online] + [
            dict(row, offline=True) for row in offline
        ]

    async def check(self, principal: KeycloakPrincipal) -> None:
        if not principal.sid:
            raise AuthenticationError("Sign in again", code="reauthentication_required")
        user = await self.request("GET", f"/users/{quote(principal.sub, safe='')}")
        if not user or not user.get("enabled"):
            raise AuthenticationError("Account is disabled")
        if not any(row["id"] == principal.sid for row in await self.sessions(principal.sub)):
            raise AuthenticationError("Authentication session was revoked")

    async def terminate(self, payload: dict) -> None:
        scope = payload["scope"]
        if scope == "delete_account":
            await self.request("DELETE", f"/users/{quote(payload['subject'], safe='')}")
            return
        if scope not in {"current", "all"}:
            raise ValueError("Unsupported remote operation")
        # Persisted identifiers are the authoritative targets. Never broaden a retry
        # into a user-wide logout, which could terminate a subsequent login.
        for sid in payload["session_ids"]:
            if sid == payload.get("preserve_session_id"):
                continue
            path = f"/sessions/{quote(sid, safe='')}"
            await self.request("DELETE", path, params={"isOffline": "false"})
            await self.request("DELETE", path, params={"isOffline": "true"})

    async def browser_logout_url(self) -> str:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(settings.keycloak.well_known_url)
                response.raise_for_status()
                endpoint = response.json()["end_session_endpoint"]
            expected = settings.keycloak.issuer.rstrip("/") + "/protocol/openid-connect/logout"
            if endpoint != expected:
                raise ValueError("Unexpected end-session endpoint")
            return (
                endpoint
                + "?"
                + urlencode(
                    {
                        "client_id": settings.keycloak.web_client_id,
                        "post_logout_redirect_uri": settings.auth.post_logout_redirect_url,
                    }
                )
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise HTTPException(503, detail={"code": "auth_provider_unavailable"}) from exc


session_control = SessionControl()
