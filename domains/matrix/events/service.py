"""Sensitive Matrix events must be encrypted by the authenticated browser SDK."""

from typing import Any

from fastapi import HTTPException


class MatrixBusinessEventService:
    async def publish(self, **kwargs: Any) -> dict:
        raise HTTPException(410, detail={"code": "matrix_client_encryption_required"})


matrix_business_event_service = MatrixBusinessEventService()
