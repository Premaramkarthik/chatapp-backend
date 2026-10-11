"""Durable, scoped remote termination after local revocation commits."""

import asyncio

from fastapi import HTTPException

from infrastructure.database.connection import get_pool
from infrastructure.keycloak.session_control import session_control


async def complete_operation(operation_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT * FROM auth_remote_operations WHERE id=$1::uuid FOR UPDATE SKIP LOCKED",
            operation_id,
        )
        if row is None:
            return False
        if row["status"] == "complete":
            return True
        payload = row["payload"]
        try:
            from infrastructure.matrix.admin import synapse_admin_client

            if payload.get("matrix_logout_token"):
                import httpx

                from core.config.settings import settings
                from domains.auth.security import TokenCipher

                async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as http:
                    response = await http.post(
                        f'{settings.matrix.homeserver_url.rstrip("/")}/_matrix/client/v3/logout',
                        headers={
                            "Authorization": "Bearer "
                            + TokenCipher().decrypt(payload["matrix_logout_token"])
                        },
                        json={},
                    )
                    if response.status_code != 401:
                        response.raise_for_status()
            for target in payload.get("matrix_devices", []):
                await synapse_admin_client.delete_device(
                    mxid=target["mxid"], device_id=target["device_id"]
                )
            if payload.get("matrix_account"):
                await synapse_admin_client.deactivate_user(mxid=payload["matrix_account"])
            if payload.get("scope") != "matrix_devices":
                await session_control.terminate(payload)
        except Exception as exc:
            # Store only the exception class, never provider response bodies or tokens.
            await conn.execute(
                """UPDATE auth_remote_operations SET attempts=attempts+1, last_error=$2,
                next_attempt_at=now()+make_interval(
                    secs => LEAST(300, power(2, LEAST(attempts,8))::int))
                WHERE id=$1::uuid""",
                operation_id,
                type(exc).__name__,
            )

            return False
        if payload.get("scope") == "delete_account":
            await conn.execute(
                "DELETE FROM users WHERE id=$1::uuid AND status='deleted'", payload["user_id"]
            )
        await conn.execute(
            "UPDATE auth_remote_operations SET status='complete', completed_at=now() "
            "WHERE id=$1::uuid",
            operation_id,
        )

        return True


async def result_for(operation_id: str, *, count: int = 0) -> dict:
    try:
        complete = await complete_operation(operation_id)
    except Exception:
        # The durable operation already exists; worker will retry even if marking success failed.
        complete = False
    return {
        "local_revocation": "complete",
        "remote_termination": "complete" if complete else "pending",
        "operation_id": operation_id,
        "revoked_count": count,
    }


async def run_remote_operations(stop: asyncio.Event) -> None:
    from core.logging.logger import get_logger

    logger = get_logger(__name__)
    while not stop.is_set():
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id FROM auth_remote_operations WHERE status='pending' "
                    "AND next_attempt_at<=now() LIMIT 50"
                )
            async with pool.acquire() as conn, conn.transaction():
                expired = await conn.fetch("""UPDATE matrix_sessions m SET status='revoked'
                FROM auth_sessions a WHERE m.bff_session_id=a.id AND m.status='active'
                AND (a.status NOT IN ('ACTIVE','REFRESHING') OR a.max_expires_at<=now()
                     OR a.idle_expires_at<=now()) RETURNING m.mxid,m.device_id""")
                if expired:
                    await conn.execute(
                        "INSERT INTO auth_remote_operations(payload) VALUES($1::jsonb)",
                        {"scope": "matrix_devices", "matrix_devices": [dict(d) for d in expired]},
                    )
            for row in rows:
                await complete_operation(str(row["id"]))
            from domains.matrix.rooms.service import retry_room_operations

            await retry_room_operations()
        except Exception as exc:
            logger.warning("Security operation worker failed: {}", type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            pass


def unavailable_local(exc: Exception) -> HTTPException:
    return HTTPException(503, detail={"code": "local_revocation_failed"})
