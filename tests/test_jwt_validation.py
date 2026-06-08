"""JWT validation tests with Redis JWKS cache."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from infrastructure.keycloak.adapter import KeycloakVerifier, _signing_key_from_jwks
from v1.utils.base import AuthenticationError


def _rsa_jwks_and_token(*, issuer: str, audience: str, expired: bool = False) -> tuple[dict, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )
    public_numbers = private_key.public_key().public_numbers()
    n = jwt.utils.base64url_encode(public_numbers.n.to_bytes(256, "big")).decode()
    e = jwt.utils.base64url_encode(public_numbers.e.to_bytes(3, "big")).decode()
    jwks = {
        "keys": [{"kty": "RSA", "kid": "test-kid", "n": n, "e": e, "alg": "RS256", "use": "sig"}]
    }
    now = int(time.time())
    exp = now - 60 if expired else now + 3600
    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": issuer,
            "aud": audience,
            "exp": exp,
            "email_verified": True,
            "realm_access": {"roles": []},
            "resource_access": {},
        },
        private_pem,
        algorithm="RS256",
        headers={"kid": "test-kid"},
    )
    return jwks, token


@pytest.mark.asyncio
async def test_verify_token_uses_redis_jwks() -> None:
    """Verifier reads JWKS from Redis before live fetch."""
    from core.config.settings import settings

    jwks, token = _rsa_jwks_and_token(
        issuer=settings.keycloak.issuer,
        audience=settings.keycloak.audience,
    )
    verifier = KeycloakVerifier()

    with patch(
        "infrastructure.keycloak.adapter.auth_redis_cache.get_json",
        new=AsyncMock(return_value=jwks),
    ):
        principal = await verifier.verify_token(token)

    assert principal.sub == "user-1"
    assert principal.email_verified is True


@pytest.mark.asyncio
async def test_verify_token_rejects_expired_token() -> None:
    """Expired tokens are rejected."""
    from core.config.settings import settings

    jwks, token = _rsa_jwks_and_token(
        issuer=settings.keycloak.issuer,
        audience=settings.keycloak.audience,
        expired=True,
    )
    verifier = KeycloakVerifier()

    with patch(
        "infrastructure.keycloak.adapter.auth_redis_cache.get_json",
        new=AsyncMock(return_value=jwks),
    ):
        with pytest.raises(AuthenticationError):
            await verifier.verify_token(token)


def test_signing_key_from_jwks_matches_kid() -> None:
    """JWKS kid selection returns a PyJWK."""
    from core.config.settings import settings

    jwks, token = _rsa_jwks_and_token(
        issuer=settings.keycloak.issuer,
        audience=settings.keycloak.audience,
    )
    key = _signing_key_from_jwks(jwks, token)
    assert key.key_id == "test-kid"
