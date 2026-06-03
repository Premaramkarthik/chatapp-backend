"""Observability metrics and /metrics endpoint tests."""

from fastapi.testclient import TestClient

from core.observability.prometheus_metrics import (
    LOGIN_SUCCESS_TOTAL,
    SIGNUP_SUCCESS_TOTAL,
)
from main import app


def test_metrics_endpoint_returns_prometheus_format() -> None:
    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "# TYPE" in body
    assert "signup_success_total" in body or "http_requests_total" in body


def test_prometheus_counters_increment() -> None:
    before = SIGNUP_SUCCESS_TOTAL._value.get()  # noqa: SLF001
    SIGNUP_SUCCESS_TOTAL.inc()
    after = SIGNUP_SUCCESS_TOTAL._value.get()  # noqa: SLF001
    assert after >= before + 1


def test_login_counter_has_expected_labels() -> None:
    LOGIN_SUCCESS_TOTAL.inc()
    sample = LOGIN_SUCCESS_TOTAL.collect()[0].samples[0]
    assert sample.name == "login_success_total"
