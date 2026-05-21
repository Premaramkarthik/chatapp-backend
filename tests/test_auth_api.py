"""Auth route tests."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import app
from v1.dependencies.container import get_auth_service
from v1.services.auth.models import SignupResult
from v1.services.auth.service import SigninStartResult


class FakeAuthService:
    async def start_signin(self, *, post_signin_redirect_uri, request):
        return SigninStartResult(
            authorization_url="http://keycloak.test/auth?state=abc",
            state="abc",
            expires_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def forgot_password(self, *, email: str, request) -> None:
        return None

    async def signup(
        self,
        *,
        email,
        display_name,
        account_mode,
        device_fingerprint,
        captcha_token,
        idempotency_key,
        request,
    ):
        return SignupResult()

    async def resend_signup_email(self, *, email: str, request):
        return SignupResult()

    async def start_social_signup(
        self,
        *,
        identity_provider,
        account_mode,
        device_fingerprint,
        captcha_token,
        post_signin_redirect_uri,
        request,
    ):
        return SigninStartResult(
            authorization_url=f"http://keycloak.test/auth?kc_idp_hint={identity_provider}",
            state="social-state",
            expires_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_signin_start_route_returns_authorization_url() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post("/v1/auth/signin/start", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["authorization_url"] == "http://keycloak.test/auth?state=abc"


def test_forgot_password_response_is_generic() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/forgot-password",
                json={"email": "user@example.com"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_signup_requires_idempotency_key() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signup",
                json={
                    "email": "user@example.com",
                    "display_name": "User Example",
                    "account_mode": "traveler",
                    "device_fingerprint": "device-12345",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_signup_returns_generic_accepted_response() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signup",
                headers={"Idempotency-Key": "signup-key-1"},
                json={
                    "email": "user@example.com",
                    "display_name": "User Example",
                    "account_mode": "both",
                    "device_fingerprint": "device-12345",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "next_step": "check_email"}


def test_social_signup_start_returns_idp_authorization_url() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signup/social/start",
                json={
                    "identity_provider": "google",
                    "account_mode": "messenger",
                    "device_fingerprint": "device-12345",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "kc_idp_hint=google" in response.json()["authorization_url"]
