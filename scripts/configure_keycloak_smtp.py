#!/usr/bin/env python3
"""Apply Gmail (or other) SMTP settings to a Keycloak realm via Admin API."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    """Load repo-root .env so `uv run` picks up KEYCLOAK_SMTP_* without manual export."""
    load_dotenv(REPO_ROOT / ".env", override=False)


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _client_credentials_token(
    *,
    base_url: str,
    realm: str,
    client_id: str,
    client_secret: str,
) -> str:
    token_url = f"{base_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    with httpx.Client(timeout=15.0) as client:
        response = client.post(token_url, data=payload)
        response.raise_for_status()
        return str(response.json()["access_token"])


def _master_admin_token(*, base_url: str, username: str, password: str) -> str:
    """Master-realm admin token; required for realm SMTP updates (manage-realm)."""
    token_url = f"{base_url.rstrip('/')}/realms/master/protocol/openid-connect/token"
    payload = {
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": username,
        "password": password,
    }
    with httpx.Client(timeout=15.0) as client:
        response = client.post(token_url, data=payload)
        response.raise_for_status()
        return str(response.json()["access_token"])


def _admin_token(*, base_url: str, realm: str, client_id: str, client_secret: str) -> str:
    return _client_credentials_token(
        base_url=base_url,
        realm=realm,
        client_id=client_id,
        client_secret=client_secret,
    )


def _bootstrap_admin_token(*, base_url: str) -> str | None:
    bootstrap_user = os.getenv("KEYCLOAK_BOOTSTRAP_ADMIN")
    bootstrap_password = os.getenv("KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD")
    if not bootstrap_user or not bootstrap_password:
        return None
    return _master_admin_token(
        base_url=base_url,
        username=bootstrap_user,
        password=bootstrap_password,
    )


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


def _apply_realm_smtp(
    *,
    client: httpx.Client,
    admin_realm_url: str,
    headers: dict[str, str],
    smtp_server: dict[str, str],
) -> None:
    get_response = client.get(admin_realm_url, headers=headers)
    get_response.raise_for_status()
    realm_payload = get_response.json()
    realm_payload["smtpServer"] = smtp_server
    put_response = client.put(admin_realm_url, headers=headers, json=realm_payload)
    put_response.raise_for_status()


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


def configure_smtp(*, test_connection: bool) -> None:
    base_url = _env("KEYCLOAK_BASE_URL", "http://localhost:8080")
    realm = _env("KEYCLOAK_REALM", "chatapp")
    admin_client_id = _env("KEYCLOAK_ADMIN_CLIENT_ID", "chatapp-backend-admin")
    admin_client_secret = _env("KEYCLOAK_ADMIN_CLIENT_SECRET", "change-me")

    smtp_server = {
        "host": _env("KEYCLOAK_SMTP_HOST", "smtp.gmail.com"),
        "port": _env("KEYCLOAK_SMTP_PORT", "587"),
        "from": _env("KEYCLOAK_SMTP_FROM"),
        "fromDisplayName": os.getenv("KEYCLOAK_SMTP_FROM_DISPLAY_NAME", "PariPath ChatApp"),
        "auth": "true",
        "user": _env("KEYCLOAK_SMTP_USER"),
        "password": _env("KEYCLOAK_SMTP_PASSWORD"),
        "starttls": os.getenv("KEYCLOAK_SMTP_STARTTLS", "true"),
        "ssl": os.getenv("KEYCLOAK_SMTP_SSL", "false"),
    }

    token = _admin_token(
        base_url=base_url,
        realm=realm,
        client_id=admin_client_id,
        client_secret=admin_client_secret,
    )
    admin_realm_url = f"{base_url.rstrip('/')}/admin/realms/{realm}"
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(timeout=15.0) as client:
        try:
            _apply_realm_smtp(
                client=client,
                admin_realm_url=admin_realm_url,
                headers=headers,
                smtp_server=smtp_server,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 403:
                raise
            bootstrap_token = _bootstrap_admin_token(base_url=base_url)
            if bootstrap_token is None:
                raise SystemExit(
                    "Keycloak returned 403: chatapp-backend-admin needs realm-management "
                    "roles view-realm and manage-realm. Restart Keycloak to re-import "
                    "docker/keycloak/realm-chatapp.json, or set KEYCLOAK_BOOTSTRAP_ADMIN "
                    "and KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD (docker-compose uses admin/admin)."
                ) from exc
            headers = {"Authorization": f"Bearer {bootstrap_token}"}
            _apply_realm_smtp(
                client=client,
                admin_realm_url=admin_realm_url,
                headers=headers,
                smtp_server=smtp_server,
            )

        if test_connection:
            bootstrap_token = _bootstrap_admin_token(base_url=base_url)
            if bootstrap_token is None:
                raise SystemExit(
                    "SMTP test requires KEYCLOAK_BOOTSTRAP_ADMIN and "
                    "KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD (docker-compose uses admin/admin)."
                )
            test_headers = {"Authorization": f"Bearer {bootstrap_token}"}
            test_recipient = os.getenv("KEYCLOAK_SMTP_TEST_TO") or smtp_server["user"]
            _ensure_bootstrap_admin_email(
                client=client,
                base_url=base_url,
                headers=test_headers,
                email=test_recipient,
            )
            _test_smtp_connection(
                client=client,
                admin_realm_url=admin_realm_url,
                headers=test_headers,
                smtp_server=smtp_server,
            )

    message = f"Configured SMTP for realm '{realm}' on {base_url}"
    if test_connection:
        message += f" (test email sent to {test_recipient})"
    print(message)


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
        configure_smtp(test_connection=args.test)
    except httpx.HTTPError as exc:
        print(f"Keycloak SMTP configuration failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
