"""Callback authenticity and verified-email linking."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from domains.auth.security import TokenCipher, hash_secret
from domains.auth.service import AuthService
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.base import AuthenticationError


@pytest.mark.asyncio
async def test_unverified_callback_cannot_link_local_user():
    repo = SimpleNamespace(resolve_verified_identity=AsyncMock())
    service = AuthService(user_repository=repo)
    with pytest.raises(AuthenticationError):
        await service._activate_or_reject_signin(
            KeycloakPrincipal(sub="subject", email="user@example.com", email_verified=False),
            None,
            None,
        )
    repo.resolve_verified_identity.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_rejects_nonce_before_linking(monkeypatch):
    from domains.auth import service as module

    cipher = TokenCipher("test-encryption")
    state = SimpleNamespace(
        code_verifier_encrypted=cipher.encrypt("verifier"),
        nonce_hash=hash_secret("expected"),
        redirect_uri="https://api.test/callback",
        post_signin_redirect_uri="https://app.test/callback",
    )
    auth = SimpleNamespace(consume_signin_state=AsyncMock(return_value=state))
    tokens = SimpleNamespace(id_token="id", access_token="access")
    keycloak = SimpleNamespace(exchange_code=AsyncMock(return_value=tokens))
    monkeypatch.setattr(
        module.keycloak_verifier,
        "verify_id_token",
        AsyncMock(return_value={"nonce": "wrong", "sub": "subject"}),
    )
    repo = SimpleNamespace(resolve_verified_identity=AsyncMock())
    service = AuthService(
        auth_repository=auth, user_repository=repo, keycloak=keycloak, cipher=cipher
    )
    with pytest.raises(AuthenticationError):
        await service.handle_callback(
            code="code", state="state", request=Request({"type": "http", "headers": []})
        )
    repo.resolve_verified_identity.assert_not_awaited()
