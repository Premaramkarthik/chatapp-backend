"""Keycloak JWT verification and OIDC health helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import InvalidTokenError, PyJWK, PyJWKClient

from core.config.settings import settings
from core.logging.logger import get_logger, log_debug, log_warning
from infrastructure.redis.cache import auth_redis_cache
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.base import AuthenticationError

logger = get_logger(__name__)


@dataclass
class KeycloakHealth:
    """Keycloak health check result."""

    ok: bool
    detail: str


class KeycloakVerifier:
    """Async wrapper around JWKS-based JWT verification with Redis cache fallback."""

    def __init__(self) -> None:
        self._jwks_client = PyJWKClient(
            settings.keycloak.jwks_url,
            cache_keys=True,
            lifespan=settings.keycloak.jwks_cache_ttl_sec,
        )

    async def verify_token(self, token: str) -> KeycloakPrincipal:
        """Verify a Keycloak access token and return normalized principal claims."""
        try:
            signing_key = await self._resolve_signing_key(token)
            claims = await asyncio.to_thread(
                jwt.decode,
                token,
                signing_key.key,
                algorithms=settings.keycloak.algorithms,
                audience=settings.keycloak.audience,
                issuer=settings.keycloak.issuer,
                leeway=settings.jwt.clock_leeway_sec,
            )
        except InvalidTokenError as exc:
            log_warning(
                logger,
                "Keycloak access token was rejected",
                error_type=type(exc).__name__,
            )
            raise AuthenticationError("Invalid authentication token") from exc

        roles = _extract_roles(claims)
        email_verified = bool(claims.get("email_verified", False))
        log_debug(
            logger,
            "Keycloak access token verified",
            sub=claims.get("sub"),
            email_verified=email_verified,
        )
        return KeycloakPrincipal(
            sub=str(claims["sub"]),
            email=claims.get("email"),
            email_verified=email_verified,
            display_name=claims.get("name"),
            preferred_username=claims.get("preferred_username"),
            identity_provider=claims.get("identity_provider") or claims.get("idp"),
            roles=roles,
            sid=claims.get("sid") or claims.get("session_state"),
            auth_time=claims.get("auth_time"),
        )

    async def verify_id_token(self, token: str | None) -> dict:
        if not token:
            raise AuthenticationError("Missing ID token")
        try:
            key = await self._resolve_signing_key(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=settings.keycloak.algorithms,
                audience=settings.keycloak.web_client_id,
                issuer=settings.keycloak.issuer,
                options={"require": ["exp", "iat", "sub", "nonce"]},
                leeway=settings.jwt.clock_leeway_sec,
            )
            if (
                claims.get("azp", settings.keycloak.web_client_id)
                != settings.keycloak.web_client_id
            ):
                raise AuthenticationError("Invalid ID token client")
            return claims
        except InvalidTokenError as exc:
            raise AuthenticationError("Invalid ID token") from exc

    async def _resolve_signing_key(self, token: str) -> Any:
        """Resolve signing key from Redis JWKS, stale cache, or live JWKS."""
        jwks = await self._load_jwks_from_redis(stale=False)
        if jwks is None:
            jwks = await self._load_jwks_from_redis(stale=True)
        if jwks is not None:
            try:
                return _signing_key_from_jwks(jwks, token)
            except InvalidTokenError:
                log_debug(logger, "Cached JWKS did not match token; falling back to live JWKS")

        return await asyncio.to_thread(
            self._jwks_client.get_signing_key_from_jwt,
            token,
        )

    async def _load_jwks_from_redis(self, *, stale: bool) -> dict[str, Any] | None:
        key = (
            f"auth:jwks:stale:{settings.keycloak.realm}"
            if stale
            else f"auth:jwks:{settings.keycloak.realm}"
        )
        return await auth_redis_cache.get_json(key)

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
            async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
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
            log_warning(
                logger,
                "Keycloak JWKS refresh failed",
                error_type=type(exc).__name__,
            )
            raise


def _extract_roles(claims: dict[str, Any]) -> list[str]:
    realm_roles = claims.get("realm_access", {}).get("roles", [])
    resource_access = claims.get("resource_access", {})
    client_roles: list[str] = []
    for access in resource_access.values():
        client_roles.extend(access.get("roles", []))
    return sorted({*realm_roles, *client_roles})


def _signing_key_from_jwks(jwks: dict[str, Any], token: str) -> PyJWK:
    """Pick the JWK matching the token kid from a JWKS document."""
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    keys = jwks.get("keys", [])
    for key in keys:
        if kid is None or key.get("kid") == kid:
            return PyJWK(key)
    raise InvalidTokenError("Unable to find a signing key that matches")


keycloak_verifier = KeycloakVerifier()
