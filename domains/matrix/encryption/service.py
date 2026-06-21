"""Matrix E2EE device and key backup metadata."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb
from infrastructure.database.repositories.matrix_devices import PostgresMatrixDeviceRepository


class MatrixEncryptionService:
    """Manage device trust metadata and key backup records."""

    def __init__(self, *, devices: PostgresMatrixDeviceRepository | None = None) -> None:
        self._devices = devices or PostgresMatrixDeviceRepository()

    async def list_devices(self, user_id: str) -> list[dict[str, Any]]:
        """List known devices for a user."""
        return await self._devices.list_for_user(user_id)

    async def register_device(
        self,
        *,
        user_id: str,
        device_id: str,
        device_label: str | None = None,
    ) -> dict[str, Any]:
        """Upsert device metadata from client registration."""
        return await self._devices.upsert(
            user_id=user_id,
            device_id=device_id,
            device_label=device_label,
        )

    async def verify_device(
        self,
        *,
        user_id: str,
        device_id: str,
    ) -> dict[str, Any]:
        """Mark a device as verified."""
        return await self._devices.verify(user_id=user_id, device_id=device_id)

    async def delete_device(self, *, user_id: str, device_id: str) -> dict[str, Any] | None:
        """Remove device metadata."""
        return await self._devices.delete(user_id=user_id, device_id=device_id)

    async def init_key_backup(
        self,
        *,
        user_id: str,
        backup_version: str,
        algorithm: str = "m.megolm_backup.v1",
    ) -> dict[str, Any]:
        """Record key backup initialization metadata."""
        result = await call_json_function(
            "fn_matrix_key_backup_metadata",
            1,
            {
                "user_id": user_id,
                "backup_version": backup_version,
                "algorithm": algorithm,
            },
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_key_backup_metadata mode 1 returned no row")
        return row

    async def list_key_backups(self, user_id: str) -> list[dict[str, Any]]:
        """List key backup metadata versions for a user."""
        result = await call_json_function(
            "fn_matrix_key_backup_metadata",
            2,
            {"user_id": user_id},
        )
        return list_from_jsonb(result)

    async def cross_signing_status(self, user_id: str) -> dict[str, Any]:
        """Return a coarse cross-signing readiness summary from device trust."""
        devices = await self.list_devices(user_id)
        verified = [d for d in devices if d.get("trust_level") == "verified"]
        return {
            "cross_signing_ready": len(verified) > 0,
            "verified_device_count": len(verified),
            "device_count": len(devices),
        }

    async def revoke_device(self, user_id: str, device_id: str) -> None:
        """Remove device metadata or raise when missing."""
        row = await self.delete_device(user_id=user_id, device_id=device_id)
        if row is None:
            raise ValueError("Device not found")

    async def record_verify_session(self, user_id: str, device_id: str) -> dict[str, Any] | None:
        """Mark a device verified and return updated metadata."""
        try:
            return await self.verify_device(user_id=user_id, device_id=device_id)
        except RuntimeError:
            return None

    async def record_key_backup_init(
        self,
        *,
        user_id: str,
        backup_version: str,
        algorithm: str = "m.megolm_backup.v1",
    ) -> dict[str, Any]:
        """Record key backup initialization metadata."""
        return await self.init_key_backup(
            user_id=user_id,
            backup_version=backup_version,
            algorithm=algorithm,
        )

    async def record_key_backup_restore(
        self,
        *,
        user_id: str,
        backup_version: str,
    ) -> dict[str, Any] | None:
        """Return backup metadata for a restore audit event."""
        for row in await self.list_key_backups(user_id):
            if row.get("backup_version") == backup_version:
                return row
        return None

    async def record_cross_signing_status(
        self,
        *,
        user_id: str,
        bootstrapped: bool,
    ) -> dict[str, Any]:
        """Record coarse cross-signing bootstrap status."""
        status = await self.cross_signing_status(user_id)
        status["bootstrapped"] = bootstrapped
        return status


matrix_encryption_service = MatrixEncryptionService()
