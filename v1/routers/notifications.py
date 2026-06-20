"""In-app notification routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from infrastructure.database.repositories.notifications import PostgresNotificationRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from v1.dependencies.auth import get_current_principal, require_capability
from v1.schemas.notifications import NotificationResponse
from v1.schemas.principal import KeycloakPrincipal

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
MessageSender = Annotated[KeycloakPrincipal, Depends(require_capability("message:send"))]


async def _local_user_id(principal: KeycloakPrincipal) -> str:
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user.id


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    _: MessageSender,
    principal: CurrentPrincipal,
    unread_only: bool = Query(False),
) -> list[NotificationResponse]:
    """List notifications for the current user."""
    user_id = await _local_user_id(principal)
    rows = await PostgresNotificationRepository().list_notifications(
        user_id,
        unread_only=unread_only,
    )
    return [NotificationResponse(**row) for row in rows]


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> NotificationResponse:
    """Mark a notification as read."""
    user_id = await _local_user_id(principal)
    row = await PostgresNotificationRepository().mark_read(user_id, str(notification_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return NotificationResponse(**row)
