"""Security regressions for real-device ownership, callbacks and scoped termination."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from domains.auth.security import TokenCipher
from domains.matrix.session.service import MatrixSessionNotReadyError, MatrixSessionService
from infrastructure.matrix.admin import SynapseAdminClient
from v1.utils.base import MatrixIntegrationError


class Connection:
    def __init__(self, row=None):
        self.row = row
        self.execute = AsyncMock()
        self.fetch = AsyncMock(return_value=[])
        self.fetchval = AsyncMock(return_value=uuid4())

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self, query, *args):
        if query.startswith("UPDATE matrix_login_attempts"):
            row, self.row = self.row, None
            return row
        return self.row


class Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


def database(monkeypatch, module, conn):
    monkeypatch.setattr(module + ".get_pool", AsyncMock(return_value=Pool(conn)))


@pytest.mark.asyncio
async def test_callback_single_use_and_identity_binding(monkeypatch):
    conn = Connection({"user_id": uuid4(), "mxid": "@stable:matrix.local", "device_id": "device-1"})
    database(monkeypatch, "domains.matrix.session.service", conn)
    exchange = AsyncMock(
        return_value={
            "user_id": "@stable:matrix.local",
            "device_id": "device-1",
            "access_token": "private-token",
        }
    )
    monkeypatch.setattr("domains.matrix.session.service.matrix_request", exchange)
    service = MatrixSessionService()
    await service.complete_login(state="state", login_token="one-use", bff_session_id=str(uuid4()))
    insert = next(
        call
        for call in conn.execute.call_args_list
        if "INSERT INTO matrix_sessions" in " ".join(call.args[0].split())
    )
    assert "private-token" not in insert.args
    assert TokenCipher().decrypt(insert.args[5]) == "private-token"
    with pytest.raises(HTTPException) as error:
        await service.complete_login(
            state="state", login_token="one-use", bff_session_id=str(uuid4())
        )
    assert error.value.status_code == 400
    assert exchange.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "credentials",
    [
        {"user_id": "@wrong:matrix.local", "device_id": "device-1"},
        {"user_id": "@stable:matrix.local", "device_id": None},
    ],
)
async def test_callback_rejects_wrong_identity_or_missing_device(monkeypatch, credentials):
    conn = Connection({"user_id": uuid4(), "mxid": "@stable:matrix.local", "device_id": "device-1"})
    database(monkeypatch, "domains.matrix.session.service", conn)
    monkeypatch.setattr(
        "domains.matrix.session.service.matrix_request", AsyncMock(return_value=credentials)
    )
    with pytest.raises(HTTPException) as error:
        await MatrixSessionService().complete_login(
            state="state", login_token="token", bff_session_id=str(uuid4())
        )
    assert error.value.detail["code"] == "matrix_identity_mismatch"
    assert not any(
        "INSERT INTO matrix_sessions" in " ".join(call.args[0].split())
        for call in conn.execute.call_args_list
    )


@pytest.mark.asyncio
async def test_revoked_bff_never_exchanges_login_token(monkeypatch):
    conn = Connection({"user_id": uuid4(), "mxid": "@stable:matrix.local", "device_id": "device-1"})
    conn.fetchval = AsyncMock(return_value=None)
    database(monkeypatch, "domains.matrix.session.service", conn)
    exchange = AsyncMock()
    monkeypatch.setattr("domains.matrix.session.service.matrix_request", exchange)
    with pytest.raises(HTTPException) as error:
        await MatrixSessionService().complete_login(
            state="state", login_token="token", bff_session_id=str(uuid4())
        )
    assert error.value.status_code == 401
    exchange.assert_not_called()


@pytest.mark.asyncio
async def test_session_never_falls_back_to_impersonation(monkeypatch):
    database(monkeypatch, "domains.matrix.session.service", Connection())
    with pytest.raises(MatrixSessionNotReadyError):
        await MatrixSessionService().create_session(
            user={"id": str(uuid4())}, bff_session_id=str(uuid4())
        )


@pytest.mark.asyncio
async def test_attachment_authorization_denies_unrelated_room(monkeypatch):
    from domains.matrix.search.service import MatrixSearchService

    monkeypatch.setattr("domains.matrix.authorization.fetchrow", AsyncMock(return_value=None))
    repo = AsyncMock()
    service = MatrixSearchService(attachments=repo)
    with pytest.raises(HTTPException) as error:
        await service.record_attachment_metadata(
            room_id="!private:matrix.local", event_id="$event", uploaded_by_user_id=str(uuid4())
        )
    assert error.value.status_code == 403
    repo.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_remote_matrix_retry_is_scoped_and_durable(monkeypatch):
    from domains.auth.remote_operations import complete_operation

    conn = Connection(
        {
            "status": "pending",
            "payload": {
                "scope": "matrix_devices",
                "matrix_devices": [{"mxid": "@u:matrix.local", "device_id": "a"}],
            },
        }
    )
    database(monkeypatch, "domains.auth.remote_operations", conn)
    delete = AsyncMock(side_effect=MatrixIntegrationError("unavailable"))
    terminate = AsyncMock()
    monkeypatch.setattr("infrastructure.matrix.admin.synapse_admin_client.delete_device", delete)
    monkeypatch.setattr("domains.auth.remote_operations.session_control.terminate", terminate)
    assert not await complete_operation(str(uuid4()))
    delete.assert_awaited_once_with(mxid="@u:matrix.local", device_id="a")
    terminate.assert_not_called()
    assert "attempts=attempts+1" in conn.execute.call_args.args[0]
    delete.side_effect = None
    assert await complete_operation(str(uuid4()))
    terminate.assert_not_called()


@pytest.mark.asyncio
async def test_admin_device_delete_encodes_paths_and_missing_is_idempotent(monkeypatch):
    client = SynapseAdminClient(admin_token="test")
    request = AsyncMock(side_effect=MatrixIntegrationError("missing", context={"status_code": 404}))
    monkeypatch.setattr(client, "_request", request)
    await client.delete_device(mxid="@u:server", device_id="a/b")
    assert "%40u%3Aserver/devices/a%2Fb" in request.call_args.args[1]


@pytest.mark.asyncio
async def test_sensitive_server_events_are_retired():
    from domains.matrix.events.service import matrix_business_event_service

    with pytest.raises(HTTPException) as error:
        await matrix_business_event_service.publish(room_id="!r:server", payload={"secret": "body"})
    assert error.value.status_code == 410


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["invalid", "ambiguous", "malformed", "pre_exchange"])
async def test_refresh_failure_retains_only_proven_pre_exchange_tokens(monkeypatch, kind):
    import httpx

    from domains.auth.security import now_utc
    from domains.matrix.session.service import settings

    monkeypatch.setattr(settings.matrix, "enabled", True)
    cipher = TokenCipher()
    row = {
        "id": uuid4(),
        "mxid": "@u:server",
        "device_id": "device",
        "expires_at": now_utc(),
        "access_token_encrypted": cipher.encrypt("access"),
        "refresh_token_encrypted": cipher.encrypt("refresh"),
    }
    conn = Connection(row)
    database(monkeypatch, "domains.matrix.session.service", conn)
    if kind == "malformed":
        exchange = AsyncMock(return_value={"expires_in_ms": "invalid"})
    else:
        error = MatrixSessionNotReadyError("invalid") if kind == "invalid" else HTTPException(503)
        if kind == "pre_exchange":
            error.__cause__ = httpx.ConnectError("unavailable")
        exchange = AsyncMock(side_effect=error)
    monkeypatch.setattr("domains.matrix.session.service.matrix_request", exchange)
    with pytest.raises((HTTPException, MatrixSessionNotReadyError)):
        await MatrixSessionService().refresh_session(
            user={"id": str(uuid4())}, bff_session_id=str(uuid4())
        )
    revocations = [
        call for call in conn.execute.call_args_list if "SET status='revoked'" in call.args[0]
    ]
    assert bool(revocations) is (kind != "pre_exchange")
    operations = [
        call for call in conn.execute.call_args_list if "auth_remote_operations" in call.args[0]
    ]
    assert bool(operations) is (kind != "pre_exchange")


def test_callback_access_redaction_preserves_formatter_arguments():
    import logging

    from uvicorn.logging import AccessFormatter

    from core.logging.auth_redaction import CallbackRedactionFilter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/callback?loginToken=secret&state=private", "1.1", 200),
        None,
    )
    CallbackRedactionFilter().filter(record)
    rendered = AccessFormatter("%(request_line)s %(status_code)s").format(record)
    assert "secret" not in rendered and "private" not in rendered
    assert "[REDACTED]" in rendered


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/chat",
        "https://app.example/chat#token",
        "https://app.example/chat?return=evil",
    ],
)
def test_matrix_redirects_reject_unconfigured_origins_and_fragments(monkeypatch, url):
    from domains.matrix.session.service import settings, validate_matrix_urls

    monkeypatch.setattr(settings.matrix, "callback_url", "https://api.example/callback")
    monkeypatch.setattr(settings.matrix, "post_login_url", url)
    monkeypatch.setattr(settings.auth, "allowed_redirect_origins_raw", "https://app.example")
    with pytest.raises(HTTPException) as error:
        validate_matrix_urls()
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_room_alias_reconciliation_checks_participants_and_encryption(monkeypatch):
    import httpx

    import infrastructure.matrix.client as module
    from infrastructure.matrix.client import reconcile_encrypted_room

    responses = iter(
        [
            {"room_id": "!r:server"},
            [
                {
                    "type": "m.room.encryption",
                    "state_key": "",
                    "content": {"algorithm": "m.megolm.v1.aes-sha2"},
                },
                {
                    "type": "m.room.member",
                    "state_key": "@a:server",
                    "content": {"membership": "join"},
                },
                {
                    "type": "m.room.member",
                    "state_key": "@intruder:server",
                    "content": {"membership": "invite"},
                },
            ],
        ]
    )

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            return httpx.Response(200, json=next(responses), request=httpx.Request("GET", url))

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: Client())
    with pytest.raises(MatrixIntegrationError):
        await reconcile_encrypted_room(
            access_token="secret",
            room_alias="#conn:server",
            expected_members={"@a:server", "@b:server"},
        )
