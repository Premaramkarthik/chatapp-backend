"""Tests for application database endpoint selection and failover."""

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from core.config.settings import DatabaseSettings, settings
from infrastructure.database.connection import pool as database_pool
from v1.utils.base import DatabaseConnectionError


def test_database_settings_selects_pgbouncer_but_keeps_direct_dsn() -> None:
    db = DatabaseSettings(
        DB_HOST="postgres",
        DB_PORT=5432,
        DB_USER="chatapp",
        DB_PASSWORD="p@ss/word",
        DB_NAME="chatapp",
        DB_TARGET="pgbouncer",
        PGBOUNCER_HOST="localhost",
        PGBOUNCER_PORT=6432,
    )

    assert db.application_host_port == ("localhost", 6432)
    assert db.direct_dsn == "postgresql://chatapp:p%40ss%2Fword@postgres:5432/chatapp"


@pytest.mark.asyncio
async def test_pool_falls_back_to_direct_only_when_pgbouncer_connection_fails(monkeypatch) -> None:
    db = settings.database
    for name, value in {
        "target_label": "pgbouncer",
        "host": "postgres",
        "port": 5432,
        "user": "chatapp",
        "name": "chatapp",
        "pgbouncer_host": "pgbouncer",
        "pgbouncer_port": 6432,
    }.items():
        monkeypatch.setattr(db, name, value)
    monkeypatch.setattr(database_pool, "_resolved_api_pool_min_max", AsyncMock(return_value=(1, 5)))
    monkeypatch.setattr(database_pool.asyncio, "sleep", AsyncMock())

    fake_pool = MagicMock()
    fake_pool.get_size.return_value = 1
    create_pool = AsyncMock(
        side_effect=[OSError("connection refused"), fake_pool],
    )
    monkeypatch.setattr(asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(database_pool, "_db", database_pool.DatabasePool())

    pool = await database_pool.connect_to_db_with_retry(max_retries=1, delay=0)

    assert pool is fake_pool
    assert [call.kwargs["host"] for call in create_pool.await_args_list] == [
        "pgbouncer",
        "postgres",
    ]


@pytest.mark.asyncio
async def test_pool_does_not_fall_back_on_authentication_failure(monkeypatch) -> None:
    db = settings.database
    monkeypatch.setattr(db, "target_label", "pgbouncer")
    monkeypatch.setattr(db, "host", "postgres")
    monkeypatch.setattr(db, "port", 5432)
    monkeypatch.setattr(db, "pgbouncer_host", "pgbouncer")
    monkeypatch.setattr(db, "pgbouncer_port", 6432)
    monkeypatch.setattr(database_pool, "_resolved_api_pool_min_max", AsyncMock(return_value=(1, 5)))

    create_pool = AsyncMock(side_effect=asyncpg.exceptions.InvalidPasswordError("invalid"))
    monkeypatch.setattr(asyncpg, "create_pool", create_pool)

    with pytest.raises(DatabaseConnectionError, match="authentication failed"):
        await database_pool.connect_to_db_with_retry(max_retries=1, delay=0)

    create_pool.assert_awaited_once()
    assert create_pool.await_args.kwargs["host"] == "pgbouncer"


@pytest.mark.asyncio
async def test_pool_does_not_bypass_pgbouncer_client_limit(monkeypatch) -> None:
    db = settings.database
    monkeypatch.setattr(db, "target_label", "pgbouncer")
    monkeypatch.setattr(db, "host", "postgres")
    monkeypatch.setattr(db, "port", 5432)
    monkeypatch.setattr(db, "pgbouncer_host", "pgbouncer")
    monkeypatch.setattr(db, "pgbouncer_port", 6432)
    monkeypatch.setattr(database_pool, "_resolved_api_pool_min_max", AsyncMock(return_value=(1, 5)))

    create_pool = AsyncMock(
        side_effect=asyncpg.exceptions.TooManyConnectionsError("client limit")
    )
    monkeypatch.setattr(asyncpg, "create_pool", create_pool)

    with pytest.raises(DatabaseConnectionError, match="Could not connect to PgBouncer"):
        await database_pool.connect_to_db_with_retry(max_retries=1, delay=0)

    create_pool.assert_awaited_once()
    assert create_pool.await_args.kwargs["host"] == "pgbouncer"
