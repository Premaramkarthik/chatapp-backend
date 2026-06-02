"""Fixtures for integration tests against real Postgres and Keycloak."""

from __future__ import annotations

import os

import pytest

if os.getenv("INTEGRATION_TESTS") == "1":
    os.environ["KEYCLOAK_ENABLED"] = "true"
    from core import settings

    settings.app.skip_startup_integrations = False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.getenv("INTEGRATION_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="Set INTEGRATION_TESTS=1 to run integration tests")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
