"""Test environment defaults."""

import os

os.environ.setdefault("KEYCLOAK_ENABLED", "false")
os.environ.setdefault("TINODE_ENABLED", "false")
os.environ.setdefault("MEILI_ENABLED", "false")
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("DB_PASSWORD", "postgres")

from v1.core import settings  # noqa: E402

settings.app.skip_startup_integrations = True
