"""FastAPI app smoke tests."""

from fastapi.testclient import TestClient

from main import app


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


def test_docs_use_docs_specific_content_security_policy() -> None:
    with TestClient(app) as client:
        response = client.get("/docs")

    assert response.status_code == 200
    assert "https://cdn.jsdelivr.net" in response.headers["content-security-policy"]
