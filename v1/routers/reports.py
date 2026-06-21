"""User report routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from domains.matrix.moderation.service import matrix_moderation_service
from infrastructure.database.repositories.reports import PostgresReportRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from v1.dependencies.auth import get_current_principal, require_capability
from v1.schemas.principal import KeycloakPrincipal
from v1.schemas.reports import ReportCreateRequest, ReportResponse

router = APIRouter(prefix="/v1/reports", tags=["reports"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
MessageSender = Annotated[KeycloakPrincipal, Depends(require_capability("message:send"))]


async def _local_user_id(principal: KeycloakPrincipal) -> str:
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user.id


@router.post("", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def create_report(
    payload: ReportCreateRequest,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> ReportResponse:
    """Report another user."""
    reporter_id = await _local_user_id(principal)
    reported_id = str(payload.reported_id)
    if reported_id == reporter_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot report self")
    try:
        row = await PostgresReportRepository().create_report(
            reporter_id,
            reported_id,
            payload.reason,
            payload.description,
        )
    except ValueError as exc:
        if str(exc) == "cannot_report_self":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot report self",
            ) from exc
        raise
    await matrix_moderation_service.on_user_reported(
        report_id=str(row["id"]),
        reporter_id=reporter_id,
        reported_id=reported_id,
    )
    return ReportResponse(**row)


@router.get("", response_model=list[ReportResponse])
async def list_my_reports(
    _: MessageSender,
    principal: CurrentPrincipal,
) -> list[ReportResponse]:
    """List reports filed by the current user."""
    reporter_id = await _local_user_id(principal)
    rows = await PostgresReportRepository().list_reports(reporter_id)
    return [ReportResponse(**row) for row in rows]
