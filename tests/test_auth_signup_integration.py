"""Integration tests for two-step signup against real Postgres and Keycloak."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from core.config.settings import settings
from domains.auth.security import hash_secret
from infrastructure.database.connection import close_db, execute, fetchrow, init_db

pytestmark = pytest.mark.integration

VALID_PASSWORD = "SecurePassw0rd!12"
DEVICE_FINGERPRINT = "integration-device-fingerprint"


@pytest.fixture
async def integration_client() -> AsyncClient:
    transport = ASGITransport(app=__import__("main", fromlist=["app"]).app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture(autouse=True)
async def _db_lifecycle() -> None:
    await init_db()
    yield
    await close_db()


async def _fetch_user(email: str) -> dict[str, Any] | None:
    row = await fetchrow(
        """
        SELECT id, email, status, display_name, account_mode, keycloak_sub,
               email_verified, onboarding_completed_at
        FROM users
        WHERE email = $1
        """,
        email,
    )
    return None if row is None else dict(row)


async def _fetch_signup_session(user_id: str) -> dict[str, Any] | None:
    row = await fetchrow(
        """
        SELECT id, user_id, token_hash, step_completed, expires_at, revoked_at
        FROM signup_sessions
        WHERE user_id = $1::uuid
        ORDER BY created_at DESC
        LIMIT 1
        """,
        user_id,
    )
    return None if row is None else dict(row)


async def _cleanup_signup(email: str, keycloak_sub: str | None) -> None:
    await execute(
        """
        DELETE FROM signup_sessions
        WHERE user_id IN (SELECT id FROM users WHERE email = $1)
        """,
        email,
    )
    await execute("DELETE FROM users WHERE email = $1", email)
    if keycloak_sub:
        token = await _keycloak_admin_token()
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.delete(
                f"{settings.keycloak.admin_realm_url}/users/{keycloak_sub}",
                headers={"Authorization": f"Bearer {token}"},
            )


async def _keycloak_admin_token() -> str:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            settings.keycloak.token_endpoint,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.keycloak.admin_client_id,
                "client_secret": settings.keycloak.admin_client_secret_value,
            },
        )
        response.raise_for_status()
        return str(response.json()["access_token"])


async def _keycloak_user(keycloak_sub: str) -> dict[str, Any]:
    token = await _keycloak_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{settings.keycloak.admin_realm_url}/users/{keycloak_sub}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()


@pytest.mark.asyncio
async def test_signup_start_persist_expected_db_state(
    integration_client: AsyncClient,
) -> None:
    email = f"signup-{uuid.uuid4()}@example.com"
    idempotency_key = f"signup-{uuid.uuid4()}"
    keycloak_sub: str | None = None
    try:
        start_response = await integration_client.post(
            "/v1/auth/signup/start",
            headers={"Idempotency-Key": idempotency_key},
            json={
                "email": email,
                "password": VALID_PASSWORD,
                "device_fingerprint": DEVICE_FINGERPRINT,
            },
        )
        assert start_response.status_code == 202
        start_body = start_response.json()
        assert start_body["status"] == "accepted"
        assert start_body["next_step"] == "verify_email"
        signup_token = start_body.get("signup_token")
        assert signup_token is not None
        assert len(signup_token) >= 16
        assert start_body.get("expires_at") is not None

        user = await _fetch_user(email)
        assert user is not None
        assert user["status"] == "pending_verification"
        assert user["display_name"] is None
        assert user["account_mode"] is None
        assert user["keycloak_sub"] is not None
        assert user["email_verified"] is False
        keycloak_sub = str(user["keycloak_sub"])

        session = await _fetch_signup_session(str(user["id"]))
        assert session is not None
        assert session["token_hash"] == hash_secret(signup_token)
        assert session["step_completed"] == 1
        assert session["revoked_at"] is None

        kc_user = await _keycloak_user(keycloak_sub)
        assert kc_user["email"] == email
        assert kc_user["emailVerified"] is False
        assert "UPDATE_PASSWORD" not in kc_user.get("requiredActions", [])
    finally:
        await _cleanup_signup(email, keycloak_sub)


async def _mark_keycloak_email_verified(keycloak_sub: str) -> None:
    token = await _keycloak_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{settings.keycloak.admin_realm_url}/users/{keycloak_sub}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        payload = response.json()
        payload["emailVerified"] = True
        update = await client.put(
            f"{settings.keycloak.admin_realm_url}/users/{keycloak_sub}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        update.raise_for_status()


@pytest.mark.asyncio
async def test_signup_activation_after_keycloak_email_verified(
    integration_client: AsyncClient,
) -> None:
    """Simulate verified Keycloak email activating the local user via fn_users mode 10."""
    from infrastructure.database.repositories.users import PostgresUserRepository

    email = f"signup-{uuid.uuid4()}@example.com"
    idempotency_key = f"signup-{uuid.uuid4()}"
    keycloak_sub: str | None = None
    try:
        start_response = await integration_client.post(
            "/v1/auth/signup/start",
            headers={"Idempotency-Key": idempotency_key},
            json={
                "email": email,
                "password": VALID_PASSWORD,
                "device_fingerprint": DEVICE_FINGERPRINT,
            },
        )
        assert start_response.status_code == 202
        user = await _fetch_user(email)
        assert user is not None
        keycloak_sub = str(user["keycloak_sub"])
        assert user["status"] == "pending_verification"
        assert user["email_verified"] is False

        await _mark_keycloak_email_verified(keycloak_sub)
        kc_user = await _keycloak_user(keycloak_sub)
        assert kc_user["emailVerified"] is True

        repo = PostgresUserRepository()
        activated = await repo.activate_after_verified_signin(
            keycloak_sub=keycloak_sub,
            email=email,
            email_verified=True,
        )
        assert activated is not None
        assert activated.email_verified is True
        assert activated.status == "pending_profile_setup"

        user = await _fetch_user(email)
        assert user is not None
        assert user["email_verified"] is True
        assert user["status"] == "pending_profile_setup"
        assert user["onboarding_completed_at"] is None
    finally:
        await _cleanup_signup(email, keycloak_sub)


@pytest.mark.asyncio
async def test_signup_start_idempotency_replays_cached_response(
    integration_client: AsyncClient,
) -> None:
    email = f"signup-{uuid.uuid4()}@example.com"
    idempotency_key = f"signup-{uuid.uuid4()}"
    payload = {
        "email": email,
        "password": VALID_PASSWORD,
        "device_fingerprint": DEVICE_FINGERPRINT,
    }
    keycloak_sub: str | None = None
    try:
        first = await integration_client.post(
            "/v1/auth/signup/start",
            headers={"Idempotency-Key": idempotency_key},
            json=payload,
        )
        second = await integration_client.post(
            "/v1/auth/signup/start",
            headers={"Idempotency-Key": idempotency_key},
            json=payload,
        )
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json() == second.json()

        rows = await fetchrow(
            "SELECT COUNT(*) AS count FROM users WHERE email = $1",
            email,
        )
        assert rows is not None
        assert rows["count"] == 1
        user = await _fetch_user(email)
        if user and user["keycloak_sub"]:
            keycloak_sub = str(user["keycloak_sub"])
    finally:
        await _cleanup_signup(email, keycloak_sub)


@pytest.mark.asyncio
async def test_signup_start_rejects_weak_password_without_db_pollution(
    integration_client: AsyncClient,
) -> None:
    email = f"signup-{uuid.uuid4()}@example.com"
    response = await integration_client.post(
        "/v1/auth/signup/start",
        headers={"Idempotency-Key": f"signup-{uuid.uuid4()}"},
        json={
            "email": email,
            "password": "short",
            "device_fingerprint": DEVICE_FINGERPRINT,
        },
    )
    assert response.status_code == 422
    assert await _fetch_user(email) is None
    rows = await fetchrow(
        """
        SELECT COUNT(*) AS count
        FROM signup_sessions ss
        JOIN users u ON u.id = ss.user_id
        WHERE u.email = $1
        """,
        email,
    )
    assert rows is not None
    assert rows["count"] == 0
