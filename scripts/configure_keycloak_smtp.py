#!/usr/bin/env python3
"""Apply Gmail (or other) SMTP settings to a Keycloak realm via Admin API."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from infrastructure.keycloak.master_admin import get_master_admin_token  # noqa: E402
from infrastructure.keycloak.smtp_config import (  # noqa: E402
    build_smtp_server_payload,
    ensure_keycloak_smtp,
)


def _load_env() -> None:
    """Load repo-root .env so `uv run` picks up KEYCLOAK_SMTP_* without manual export."""
    load_dotenv(REPO_ROOT / ".env", override=False)


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _ensure_bootstrap_admin_email(
    *,
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    email: str,
) -> None:
    """Keycloak testSMTPConnection sends to the logged-in admin user's email."""
    bootstrap_user = _env("KEYCLOAK_BOOTSTRAP_ADMIN", "admin")
    users_url = f"{base_url.rstrip('/')}/admin/realms/master/users"
    list_response = client.get(
        users_url,
        headers=headers,
        params={"username": bootstrap_user, "exact": "true"},
    )
    list_response.raise_for_status()
    users = list_response.json()
    if not users:
        raise SystemExit(f"Bootstrap admin user '{bootstrap_user}' not found in master realm.")
    user = users[0]
    if user.get("email"):
        return
    user_id = user["id"]
    update_response = client.put(
        f"{users_url}/{user_id}",
        headers=headers,
        json={"email": email, "emailVerified": True},
    )
    update_response.raise_for_status()


def _test_smtp_connection(
    *,
    client: httpx.Client,
    admin_realm_url: str,
    headers: dict[str, str],
    smtp_server: dict[str, str],
) -> None:
    test_response = client.post(
        f"{admin_realm_url}/testSMTPConnection",
        headers=headers,
        json=smtp_server,
    )
    if test_response.status_code >= 400:
        detail = test_response.text.strip()
        if test_response.status_code == 500 and "e-mail" in detail.lower():
            raise SystemExit(
                "Keycloak SMTP test failed: master admin user has no email. "
                "Set KEYCLOAK_SMTP_USER or re-run --test "
                "(the script sets admin email automatically)."
            )
        test_response.raise_for_status()


async def configure_smtp(*, test_connection: bool) -> None:
    """Apply SMTP from settings and optionally send a Keycloak test email."""
    from core.config.settings import settings

    smtp_server = build_smtp_server_payload()
    if smtp_server is None:
        raise SystemExit(
            "SMTP is not fully configured. Set KEYCLOAK_SMTP_HOST, KEYCLOAK_SMTP_FROM, "
            "KEYCLOAK_SMTP_USER, and KEYCLOAK_SMTP_PASSWORD."
        )

    await ensure_keycloak_smtp()

    if not test_connection:
        return

    bootstrap_user = os.getenv("KEYCLOAK_BOOTSTRAP_ADMIN")
    bootstrap_password = os.getenv("KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD")
    if not bootstrap_user or not bootstrap_password:
        raise SystemExit(
            "SMTP test requires KEYCLOAK_BOOTSTRAP_ADMIN and "
            "KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD (docker-compose uses admin/admin)."
        )

    bootstrap_token = await get_master_admin_token(
        base_url=settings.keycloak.internal_base,
        username=bootstrap_user,
        password=bootstrap_password,
        timeout_seconds=15.0,
    )
    admin_realm_url = settings.keycloak.admin_realm_url
    test_headers = {"Authorization": f"Bearer {bootstrap_token}"}
    test_recipient = os.getenv("KEYCLOAK_SMTP_TEST_TO") or smtp_server["user"]

    with httpx.Client(timeout=15.0) as client:
        _ensure_bootstrap_admin_email(
            client=client,
            base_url=settings.keycloak.internal_base,
            headers=test_headers,
            email=test_recipient,
        )
        _test_smtp_connection(
            client=client,
            admin_realm_url=admin_realm_url,
            headers=test_headers,
            smtp_server=smtp_server,
        )

    print(f"Test email sent to {test_recipient}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure Keycloak realm SMTP from env vars.")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Send a Keycloak SMTP test email to KEYCLOAK_SMTP_USER (or KEYCLOAK_SMTP_TEST_TO).",
    )
    args = parser.parse_args()
    _load_env()
    try:
        asyncio.run(configure_smtp(test_connection=args.test))
        from core.config.settings import settings

        print(
            f"Configured SMTP for realm '{settings.keycloak.realm}' "
            f"on {settings.keycloak.internal_base}",
        )
    except httpx.HTTPError as exc:
        print(f"Keycloak SMTP configuration failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
