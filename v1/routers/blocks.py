"""User block routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from domains.matrix.moderation.service import matrix_moderation_service
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from v1.dependencies.auth import get_current_principal, require_capability
from v1.schemas.blocks import BlockCreateRequest, BlockResponse
from v1.schemas.principal import KeycloakPrincipal

router = APIRouter(prefix="/v1/blocks", tags=["blocks"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
MessageSender = Annotated[KeycloakPrincipal, Depends(require_capability("message:send"))]


async def _local_user_id(principal: KeycloakPrincipal) -> str:
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user.id


@router.post("", response_model=BlockResponse, status_code=status.HTTP_201_CREATED)
async def create_block(
    payload: BlockCreateRequest,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> BlockResponse:
    """Block another user."""
    blocker_id = await _local_user_id(principal)
    blocked_id = str(payload.blocked_id)
    if blocked_id == blocker_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot block self")
    row = await PostgresMatchingRepository().create_block(
        blocker_id,
        blocked_id,
        payload.reason,
    )
    await matrix_moderation_service.on_user_blocked(blocker_id=blocker_id, blocked_id=blocked_id)
    return BlockResponse(**row)


@router.get("", response_model=list[BlockResponse])
async def list_blocks(
    _: MessageSender,
    principal: CurrentPrincipal,
) -> list[BlockResponse]:
    """List users blocked by the current user."""
    blocker_id = await _local_user_id(principal)
    rows = await PostgresMatchingRepository().list_blocks(blocker_id)
    return [BlockResponse(**row) for row in rows]


@router.delete("/{blocked_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_block(
    blocked_user_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> None:
    """Unblock a user."""
    blocker_id = await _local_user_id(principal)
    row = await PostgresMatchingRepository().delete_block(blocker_id, str(blocked_user_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Block not found")
