"""Auth route tests."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from domains.auth.models import (
    AuthSession,
    AuthSessionStatus,
    SignupCompleteResult,
    SignupResult,
    SignupStartResult,
)
from domains.auth.service import SigninCallbackResult, SigninStartResult
from domains.users.user import User
from main import app
from v1.dependencies.container import get_auth_service
from v1.schemas.principal import KeycloakPrincipal


class FakeAuthService:
    async def start_signin(
        self,
        *,
        post_signin_redirect_uri,
        identity_provider=None,
        account_mode=None,
        device_fingerprint=None,
        captcha_token=None,
        request,
    ):
        if identity_provider:
            return SigninStartResult(
                authorization_url=f"http://keycloak.test/auth?kc_idp_hint={identity_provider}",
                state="social-state",
                expires_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        return SigninStartResult(
            authorization_url="http://keycloak.test/auth?state=abc",
            state="abc",
            expires_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def signin_password(self, *, email: str, password: str, remember_me: bool, request):
        if password != "SecurePassw0rd!12":
            from v1.utils.base import AuthenticationError

            raise AuthenticationError("Invalid email or password")
        now = datetime(2026, 1, 1, tzinfo=UTC)
        user = User(
            id="85fdab9e-1812-4a47-9fdf-508ffaf3002b",
            keycloak_sub="kc-sub",
            email=email,
            display_name="Test User",
            status="active",
            account_mode="traveler",
            email_verified=True,
            created_at=now,
            updated_at=now,
        )
        session = AuthSession(
            id="sess-1",
            session_hash="hash",
            user_id="user-1",
            keycloak_sub="kc-sub",
            status=AuthSessionStatus.ACTIVE,
            access_token_encrypted="enc",
            refresh_token_encrypted=None,
            id_token_encrypted=None,
            access_expires_at=now,
            refresh_expires_at=None,
            idle_expires_at=now,
            max_expires_at=now,
            csrf_token_hash=None,
            device_label=None,
            ip_hash=None,
            user_agent_hash=None,
            last_seen_at=now,
            created_at=now,
        )
        return SigninCallbackResult(
            session_token="session-token",
            csrf_token="csrf-token",
            session=session,
            post_signin_redirect_uri="http://localhost:8080/auth/callback",
            principal=KeycloakPrincipal(sub="kc-sub", email=email),
            user=user,
            cookie_max_age_sec=2592000 if remember_me else None,
        )

    async def forgot_password(self, *, email: str, request) -> None:
        return None

    async def signup_start(
        self,
        *,
        email,
        password,
        device_fingerprint,
        captcha_token,
        idempotency_key,
        request,
    ):
        return SignupStartResult()

    async def signup_complete(
        self,
        *,
        signup_token,
        display_name,
        account_mode,
        request,
    ):
        return SignupCompleteResult()

    async def resend_signup_email(self, *, email: str, request):
        return SignupResult()

    async def complete_email_verification(self, *, token: str, request):
        if token == "expired-token-123456789":
            from v1.utils.base import AuthenticationError

            raise AuthenticationError(
                "Verification link has expired",
                code="email_verification_expired",
            )
        return None

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

    async def sso_reset_url(self, *, redirect_uri: str, request):
        return f"http://keycloak.test/logout?post_logout_redirect_uri={redirect_uri}"


def test_signin_start_route_returns_authorization_url() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post("/v1/auth/signin/start", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["authorization_url"] == "http://keycloak.test/auth?state=abc"


def test_signin_start_with_google_includes_idp_hint() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signin/start",
                json={"identity_provider": "google", "device_fingerprint": "device-12345"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "kc_idp_hint=google" in response.json()["authorization_url"]


def test_sso_reset_url_returns_keycloak_logout_url() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/auth/sso-reset-url",
                params={"redirect_uri": "http://localhost:8080/auth/oauth-resume"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["url"].startswith("http://keycloak.test/logout")
    assert "post_logout_redirect_uri=" in body["url"]


def test_signin_password_sets_session_cookies() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signin/password",
                json={
                    "email": "user@example.com",
                    "password": "SecurePassw0rd!12",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["user"]["email"] == "user@example.com"
    assert body["user"]["id"] == "85fdab9e-1812-4a47-9fdf-508ffaf3002b"
    cookie_names = {c.split("=")[0] for c in response.headers.get_list("set-cookie")}
    assert "pp_session" in cookie_names
    assert "pp_csrf" in cookie_names


def test_signin_password_remember_me_sets_persistent_cookie() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signin/password",
                json={
                    "email": "user@example.com",
                    "password": "SecurePassw0rd!12",
                    "remember_me": True,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Max-Age=2592000" in ",".join(response.headers.get_list("set-cookie"))


def test_signin_password_rejects_invalid_credentials() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signin/password",
                json={
                    "email": "user@example.com",
                    "password": "wrong-password",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


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


def test_signup_is_deprecated() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Idempotency-Key": "signup-key-1"},
            json={
                "email": "user@example.com",
                "display_name": "User Example",
                "account_mode": "traveler",
                "device_fingerprint": "device-12345",
            },
        )

    assert response.status_code == 410


def test_signup_start_requires_idempotency_key() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signup/start",
                json={
                    "email": "user@example.com",
                    "password": "SecurePassw0rd!12",
                    "device_fingerprint": "device-12345",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_signup_start_returns_verify_email_step() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signup/start",
                headers={"Idempotency-Key": "signup-key-1"},
                json={
                    "email": "user@example.com",
                    "password": "SecurePassw0rd!12",
                    "device_fingerprint": "device-12345",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    body = response.json()
    assert body["next_step"] == "verify_email"
    assert body.get("signup_token") is None


def test_signup_verify_complete_returns_ok() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signup/verify/complete",
                json={"token": "valid-token-123456789"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "next_step": "signin"}


def test_signup_verify_complete_maps_expired_token() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signup/verify/complete",
                json={"token": "expired-token-123456789"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "email_verification_expired"


def test_signup_resend_returns_cooldown_sec() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signup/resend",
                json={"email": "user@example.com"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json()["cooldown_sec"] == 60


def test_signup_complete_returns_verify_email_step() -> None:
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/signup/complete",
                json={
                    "signup_token": "signup-token-abc",
                    "display_name": "User Example",
                    "account_mode": "traveler",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "next_step": "verify_email"}


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
