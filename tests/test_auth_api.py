"""Public contracts for hosted authentication and retired password endpoints."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from core.config.settings import settings
from main import app
from v1.dependencies.container import get_auth_service
from v1.routers.auth import logout


@pytest.mark.parametrize(
    "path",
    [
        "signin/password",
        "signup",
        "signup/start",
        "signup/complete",
        "signup/resend",
        "signup/verify/complete",
        "signup/social/start",
        "forgot-password",
        "reset-password/complete",
    ],
)
def test_password_routes_are_retired_without_reading_passwords(path):
    client = TestClient(app)
    response = client.post("/v1/auth/" + path, json={"password": "do-not-log"})
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "auth_flow_retired"


def test_hosted_signup_preserves_intent():
    fake = SimpleNamespace(
        start_signin=AsyncMock(
            return_value={
                "authorization_url": "https://identity.test/auth",
                "state": "state",
                "expires_at": datetime.now(UTC),
            }
        )
    )
    app.dependency_overrides[get_auth_service] = lambda: fake
    try:
        response = TestClient(app).post("/v1/auth/signin/start", json={"intent": "signup"})
        assert response.status_code == 200
        assert fake.start_signin.call_args.kwargs["intent"] == "signup"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("remote,code", [("complete", 200), ("pending", 202)])
async def test_logout_clears_cookies_only_after_local_commit(monkeypatch, remote, code):
    from starlette.responses import Response

    from infrastructure.keycloak.session_control import session_control

    monkeypatch.setattr(
        session_control,
        "browser_logout_url",
        AsyncMock(return_value="https://identity.test/logout"),
    )
    result = {"local_revocation": "complete", "remote_termination": remote, "operation_id": "op"}
    response = Response()
    await logout(None, response, None, SimpleNamespace(logout=AsyncMock(return_value=result)))
    assert response.status_code == code
    assert settings.auth.cookie_name in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_failed_local_logout_does_not_clear_cookies():
    from starlette.responses import Response

    response = Response()
    with pytest.raises(HTTPException):
        await logout(
            None, response, None, SimpleNamespace(logout=AsyncMock(side_effect=HTTPException(503)))
        )
    assert "set-cookie" not in response.headers
