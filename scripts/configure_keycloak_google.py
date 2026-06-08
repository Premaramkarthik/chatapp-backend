#!/usr/bin/env python3
"""Apply Google identity provider settings to a Keycloak realm via Admin API."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from infrastructure.keycloak.google_idp_config import ensure_keycloak_google_idp  # noqa: E402


def _load_env() -> None:
    """Load repo-root .env so `uv run` picks up KEYCLOAK_GOOGLE_* without manual export."""
    load_dotenv(REPO_ROOT / ".env", override=False)


async def configure_google_idp() -> None:
    """Configure Google IdP and web client redirect URIs from application settings."""
    from core.config.settings import settings

    if not settings.keycloak.google_client_id:
        raise SystemExit(
            "Google IdP is not configured. Set KEYCLOAK_GOOGLE_CLIENT_ID and "
            "KEYCLOAK_GOOGLE_CLIENT_SECRET in .env.",
        )

    await ensure_keycloak_google_idp()


def main() -> None:
    _load_env()
    try:
        asyncio.run(configure_google_idp())
        from core.config.settings import settings

        print(
            f"Configured Google IdP alias '{settings.keycloak.google_idp_alias}' "
            f"for realm '{settings.keycloak.realm}' on {settings.keycloak.internal_base}",
        )
    except httpx.HTTPError as exc:
        print(f"Keycloak Google IdP configuration failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
