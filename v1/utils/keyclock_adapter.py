"""Keycloak JWT verification and OIDC health helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import InvalidTokenError, PyJWKClient

from v1.core.settings import settings
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.exception import AuthenticationError
from v1.utils.logger import get_logger
from v1.utils.redis_cache import auth_redis_cache

logger = get_logger(__name__)


@dataclass
class KeycloakHealth:
    """Keycloak health check result."""

    ok: bool
    detail: str


class KeycloakVerifier:
    """Small async wrapper around PyJWT's JWKS-based verifier."""

    def __init__(self) -> None:
        self._jwks_client = PyJWKClient(
            settings.keycloak.jwks_url,
            cache_keys=True,
            lifespan=settings.keycloak.jwks_cache_ttl_sec,
        )

    async def verify_token(self, token: str) -> KeycloakPrincipal:
        """Verify a Keycloak access token and return normalized principal claims."""
        try:
            signing_key = await asyncio.to_thread(
                self._jwks_client.get_signing_key_from_jwt,
                token,
            )
            claims = await asyncio.to_thread(
                jwt.decode,
                token,
                signing_key.key,
                algorithms=settings.keycloak.algorithms,
                audience=settings.keycloak.audience,
                issuer=settings.keycloak.issuer,
            )
        except InvalidTokenError as exc:
            logger.warning("keycloak_token_rejected error_type={}", type(exc).__name__)
            raise AuthenticationError("Invalid authentication token") from exc

        roles = _extract_roles(claims)
        return KeycloakPrincipal(
            sub=str(claims["sub"]),
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified", False)),
            display_name=claims.get("name"),
            preferred_username=claims.get("preferred_username"),
            identity_provider=claims.get("identity_provider") or claims.get("idp"),
            roles=roles,
        )

    async def health(self) -> KeycloakHealth:
        """Check Keycloak discovery endpoint reachability."""
        if not settings.keycloak.enabled:
            return KeycloakHealth(ok=True, detail="disabled")

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(settings.keycloak.well_known_url)
                response.raise_for_status()
        except Exception as exc:
            return KeycloakHealth(ok=False, detail=f"{type(exc).__name__}: {exc}")
        return KeycloakHealth(ok=True, detail="ok")

    async def refresh_jwks(self) -> None:
        """Proactively fetch JWKS so key rotation failures surface early."""
        if not settings.keycloak.enabled:
            return
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(settings.keycloak.jwks_url)
                response.raise_for_status()
                jwks = response.json()
                await auth_redis_cache.set_json(
                    f"auth:jwks:{settings.keycloak.realm}",
                    jwks,
                    ttl_sec=settings.keycloak.jwks_cache_ttl_sec,
                )
                await auth_redis_cache.set_json(
                    f"auth:jwks:stale:{settings.keycloak.realm}",
                    jwks,
                    ttl_sec=settings.keycloak.stale_jwks_ttl_sec,
                )
        except Exception as exc:
            logger.warning("keycloak_jwks_refresh_failed error_type={}", type(exc).__name__)
            raise


def _extract_roles(claims: dict[str, Any]) -> list[str]:
    realm_roles = claims.get("realm_access", {}).get("roles", [])
    resource_access = claims.get("resource_access", {})
    client_roles: list[str] = []
    for access in resource_access.values():
        client_roles.extend(access.get("roles", []))
    return sorted({*realm_roles, *client_roles})


keycloak_verifier = KeycloakVerifier()
