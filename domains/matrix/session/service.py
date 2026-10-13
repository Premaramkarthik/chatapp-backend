"""Interactive Synapse SSO and encrypted, BFF-owned device sessions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx
from fastapi import HTTPException

from core.config.settings import settings
from domains.auth.security import TokenCipher, generate_token, hash_secret, now_utc
from domains.matrix.provisioning.service import MatrixProvisioningService
from infrastructure.database.connection import get_pool


class MatrixSessionNotReadyError(RuntimeError):
    """An interactive Matrix login is required."""


def validate_matrix_urls() -> None:
    """Use exact configured redirects, with HTTPS required outside development."""
    for url in (settings.matrix.callback_url, settings.matrix.post_login_url):
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.fragment
            or parsed.query
        ):
            raise HTTPException(503, detail={"code": "matrix_redirect_invalid"})
        if (
            settings.app.environment.lower() not in {"local", "development", "dev", "test"}
            and parsed.scheme != "https"
        ):
            raise HTTPException(503, detail={"code": "matrix_redirect_invalid"})
    target = urlparse(settings.matrix.post_login_url)
    if f"{target.scheme}://{target.netloc}" not in settings.auth.allowed_redirect_origins:
        raise HTTPException(503, detail={"code": "matrix_redirect_invalid"})


async def matrix_request(path: str, body: dict[str, Any]) -> dict:
    """Exchange credentials without logging tokens or provider response bodies."""
    try:
        async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
            response = await client.post(
                f'{settings.matrix.homeserver_url.rstrip("/")}/_matrix/client/v3/{path}', json=body
            )
        if response.status_code == 401 or response.status_code == 403:
            raise MatrixSessionNotReadyError("matrix_login_required")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(503, detail={"code": "matrix_provider_unavailable"}) from exc


class MatrixSessionService:
    def __init__(self, **_: Any) -> None:
        self._cipher = TokenCipher()

    async def start_login(self, *, user: dict, bff_session_id: str) -> dict:
        if not settings.matrix.enabled:
            raise MatrixSessionNotReadyError("matrix_disabled")
        validate_matrix_urls()
        mapping = await MatrixProvisioningService().ensure_user_provisioned(
            user_id=str(user["id"]), display_name=user.get("display_name")
        )
        state, device_id = generate_token(), generate_token(18)
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT id FROM users WHERE id=$1::uuid FOR UPDATE", str(user["id"]))
            active = await conn.fetchval(
                """SELECT id FROM auth_sessions WHERE id=$1::uuid AND user_id=$2::uuid AND
                status='ACTIVE' AND max_expires_at>now() AND idle_expires_at>now()""",
                bff_session_id,
                str(user["id"]),
            )
            if not active:
                raise HTTPException(401, detail={"code": "session_revoked"})
            await conn.execute(
                """INSERT INTO
                matrix_login_attempts(state_hash,bff_session_id,user_id,mxid,device_id,expires_at)
                VALUES($1,$2::uuid,$3::uuid,$4,$5,$6)""",
                hash_secret(state),
                bff_session_id,
                str(user["id"]),
                mapping["mxid"],
                device_id,
                now_utc() + timedelta(minutes=10),
            )
            # Pre-record orphan cleanup before any remote login can create a device.
            await conn.execute(
                """INSERT INTO auth_remote_operations(payload,next_attempt_at)
                VALUES($1::jsonb,now()+interval '11 minutes')""",
                {
                    "scope": "matrix_devices",
                    "state_hash": hash_secret(state),
                    "matrix_devices": [{"mxid": mapping["mxid"], "device_id": device_id}],
                },
            )
        callback = settings.matrix.callback_url + "?" + urlencode({"state": state})
        return {
            "authorization_url": f"{settings.matrix.client_homeserver_url}/_matrix/client/v3/login/"
            "sso/redirect/"
            f'{quote(settings.matrix.oidc_provider_id, safe="")}?'
            + urlencode({"redirectUrl": callback})
        }

    async def complete_login(self, *, state: str, login_token: str, bff_session_id: str) -> None:
        pool = await get_pool()
        # Single use is committed before exchange, including failed exchanges.
        async with pool.acquire() as conn:
            attempt = await conn.fetchrow(
                """UPDATE matrix_login_attempts SET consumed_at=now() WHERE state_hash=$1 AND
                bff_session_id=$2::uuid AND consumed_at IS NULL AND expires_at>now()
                RETURNING *""",
                hash_secret(state),
                bff_session_id,
            )
        if not attempt:
            raise HTTPException(400, detail={"code": "matrix_callback_invalid"})
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT id FROM users WHERE id=$1 FOR UPDATE", attempt["user_id"])
            active = await conn.fetchval(
                """SELECT id FROM auth_sessions WHERE id=$1::uuid AND status='ACTIVE' AND
                max_expires_at>now() AND idle_expires_at>now()""",
                bff_session_id,
            )
            if not active:
                raise HTTPException(401, detail={"code": "session_revoked"})
            credentials = await matrix_request(
                "login",
                {
                    "type": "m.login.token",
                    "token": login_token,
                    "device_id": attempt["device_id"],
                    "initial_device_display_name": "Veliqone browser",
                    "refresh_token": True,
                },
            )
            if (
                credentials.get("user_id") != attempt["mxid"]
                or credentials.get("device_id") != attempt["device_id"]
                or not credentials.get("access_token")
            ):
                # Login under another identity must never become an application session.
                token = credentials.get("access_token")
                if token:
                    try:
                        async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as http:
                            result = await http.post(
                                f'{settings.matrix.homeserver_url.rstrip("/")}/_matrix/client/v3/logout',
                                headers={"Authorization": f"Bearer {token}"},
                                json={},
                            )
                            result.raise_for_status()
                    except httpx.HTTPError:
                        # Store a token encrypted when the unexpected identity cannot be revoked.
                        await conn.execute(
                            "INSERT INTO auth_remote_operations(payload) VALUES($1::jsonb)",
                            {
                                "scope": "matrix_devices",
                                "matrix_logout_token": self._cipher.encrypt(token),
                            },
                        )
                # Commit cleanup before returning the mismatch error.
                mismatch = True
            else:
                mismatch = False
                old = await conn.fetch(
                    """UPDATE matrix_sessions SET status='revoked' WHERE
                    bff_session_id=$1::uuid AND status='active' RETURNING mxid,device_id""",
                    bff_session_id,
                )
                if old:
                    await conn.execute(
                        "INSERT INTO auth_remote_operations(payload) VALUES($1::jsonb)",
                        {"scope": "matrix_devices", "matrix_devices": [dict(row) for row in old]},
                    )
                expiry = (
                    now_utc() + timedelta(milliseconds=credentials["expires_in_ms"])
                    if credentials.get("expires_in_ms")
                    else None
                )
                await conn.execute(
                    """INSERT INTO
                    matrix_sessions(bff_session_id,user_id,mxid,device_id,access_token_encrypted,refresh_token_encrypted,expires_at)
                    VALUES($1::uuid,$2,$3,$4,$5,$6,$7)""",
                    bff_session_id,
                    attempt["user_id"],
                    attempt["mxid"],
                    attempt["device_id"],
                    self._cipher.encrypt(credentials["access_token"]),
                    self._cipher.encrypt(credentials.get("refresh_token")),
                    expiry,
                )
                await conn.execute(
                    """INSERT INTO matrix_user_devices(user_id,device_id,device_label,last_seen_at)
                    VALUES($1,$2,'Veliqone browser',now()) ON CONFLICT(user_id,device_id)
                    DO UPDATE SET last_seen_at=now()""",
                    attempt["user_id"],
                    attempt["device_id"],
                )
                await conn.execute(
                    """UPDATE auth_remote_operations SET status='complete',completed_at=now()
                    WHERE payload->>'state_hash'=$1""",
                    hash_secret(state),
                )
        if mismatch:
            raise HTTPException(403, detail={"code": "matrix_identity_mismatch"})

    async def create_session(
        self,
        *,
        user: dict,
        bff_session_id: str | None = None,
        request_id: str | None = None,
        force_refresh: bool = False,
    ) -> dict:
        if not settings.matrix.enabled:
            raise MatrixSessionNotReadyError("matrix_disabled")
        if not bff_session_id:
            raise MatrixSessionNotReadyError("matrix_login_required")
        pool = await get_pool()
        failure = None
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT id FROM users WHERE id=$1::uuid FOR UPDATE", str(user["id"]))
            row = await conn.fetchrow(
                """SELECT m.* FROM matrix_sessions m JOIN auth_sessions a ON
                a.id=m.bff_session_id WHERE m.bff_session_id=$1::uuid AND
                m.user_id=$2::uuid AND m.status='active' AND a.status='ACTIVE' AND
                a.max_expires_at>now() AND a.idle_expires_at>now() FOR UPDATE OF m""",
                bff_session_id,
                str(user["id"]),
            )
            if not row:
                raise MatrixSessionNotReadyError("matrix_login_required")
            row = dict(row)
            if force_refresh or (
                row["expires_at"] and row["expires_at"] <= now_utc() + timedelta(seconds=30)
            ):
                if not row["refresh_token_encrypted"]:
                    raise MatrixSessionNotReadyError("matrix_login_required")
                try:
                    refreshed = await matrix_request(
                        "refresh",
                        {"refresh_token": self._cipher.decrypt(row["refresh_token_encrypted"])},
                    )
                    if not refreshed.get("access_token"):
                        raise MatrixSessionNotReadyError("matrix_login_required")
                    next_access = self._cipher.encrypt(refreshed["access_token"])
                    next_refresh = (
                        self._cipher.encrypt(refreshed.get("refresh_token"))
                        or row["refresh_token_encrypted"]
                    )
                    next_expiry = (
                        now_utc() + timedelta(milliseconds=refreshed["expires_in_ms"])
                        if refreshed.get("expires_in_ms")
                        else None
                    )
                except Exception as exc:
                    # Only proven pre-exchange connection failures may reuse the refresh token.
                    if isinstance(exc.__cause__, (httpx.ConnectError, httpx.ConnectTimeout)):
                        raise
                    await conn.execute(
                        "UPDATE matrix_sessions SET status='revoked' WHERE id=$1", row["id"]
                    )
                    await conn.execute(
                        "INSERT INTO auth_remote_operations(payload) VALUES($1::jsonb)",
                        {
                            "scope": "matrix_devices",
                            "matrix_devices": [
                                {"mxid": row["mxid"], "device_id": row["device_id"]}
                            ],
                        },
                    )
                    failure = MatrixSessionNotReadyError("matrix_login_required")
                else:
                    row["access_token_encrypted"] = next_access
                    row["refresh_token_encrypted"] = next_refresh
                    row["expires_at"] = next_expiry
                    await conn.execute(
                        """UPDATE matrix_sessions SET
                        access_token_encrypted=$2,refresh_token_encrypted=$3,expires_at=$4
                        WHERE id=$1 AND status='active'""",
                        row["id"],
                        row["access_token_encrypted"],
                        row["refresh_token_encrypted"],
                        row["expires_at"],
                    )
            payload = {
                "homeserver_url": settings.matrix.client_homeserver_url,
                "matrix_user_id": row["mxid"],
                "user_id": str(user["id"]),
                "device_id": row["device_id"],
                "access_token": self._cipher.decrypt(row["access_token_encrypted"]),
                "expires_in": (
                    max(0, int((row["expires_at"] - now_utc()).total_seconds()))
                    if row["expires_at"]
                    else None
                ),
            }

        if failure:
            raise failure
        return payload

    async def refresh_session(self, **kwargs: Any) -> dict:
        return await self.create_session(**kwargs, force_refresh=True)


matrix_session_service = MatrixSessionService()
