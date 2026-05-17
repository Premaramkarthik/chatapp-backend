"""FastAPI app smoke tests."""

from fastapi.testclient import TestClient
from v1.app import app


def test_live_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/system/version")

    assert response.status_code == 200
    assert response.json()["name"] == "chatapp API"
