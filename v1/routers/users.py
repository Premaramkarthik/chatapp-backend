"""Current-user routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.logging.logger import get_logger, log_info
from domains.auth import AuthService
from domains.users.bootstrap import BootstrapUser
from domains.users.user import BootstrapUserCommand
from infrastructure.database.repositories import PostgresUserRepository
from infrastructure.database.repositories.discovery import PostgresDiscoveryRepository
from v1.dependencies.auth import get_current_principal, require_capability
from v1.dependencies.container import get_auth_service, get_bootstrap_user_use_case
from v1.schemas.principal import KeycloakPrincipal
from v1.schemas.users import AccountModeUpdateRequest, DisplayNameUpdateRequest, UserResponse
from v1.utils.request_context import request_id_from
from v1.utils.user_session import build_user_response

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/users", tags=["users"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
BootstrapUserUseCase = Annotated[BootstrapUser, Depends(get_bootstrap_user_use_case)]
AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
ProfileUpdater = Annotated[KeycloakPrincipal, Depends(require_capability("profile:update"))]


@router.patch("/account-mode", response_model=UserResponse)
async def update_account_mode(
    request: Request,
    payload: AccountModeUpdateRequest,
    principal: CurrentPrincipal,
    bootstrap_user: BootstrapUserUseCase,
) -> dict:
    """Update business account mode without changing Keycloak roles."""
    display_name = principal.display_name or principal.preferred_username
    await bootstrap_user.execute(
        BootstrapUserCommand(
            keycloak_sub=principal.sub,
            email=principal.email,
            display_name=display_name,
        ),
        request_id=request_id_from(request),
    )
    user = await PostgresUserRepository().update_account_mode(
        keycloak_sub=principal.sub,
        account_mode=payload.account_mode,
    )
    log_info(
        logger,
        "User account mode updated",
        request_id=request_id_from(request),
        user_id=user.id,
        account_mode=payload.account_mode,
    )
    return await build_user_response(user)


@router.patch("/display-name", response_model=UserResponse)
async def update_display_name(
    request: Request,
    payload: DisplayNameUpdateRequest,
    principal: CurrentPrincipal,
    bootstrap_user: BootstrapUserUseCase,
    auth_service: AuthServiceDependency,
) -> dict:
    """Update the authenticated user's display name."""
    display_name = principal.display_name or principal.preferred_username
    bootstrapped = await bootstrap_user.execute(
        BootstrapUserCommand(
            keycloak_sub=principal.sub,
            email=principal.email,
            display_name=display_name,
        ),
        request_id=request_id_from(request),
    )
    user_repo = PostgresUserRepository()
    updated = await user_repo.update_display_name(
        user_id=bootstrapped.id,
        display_name=payload.display_name,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await auth_service.sync_display_name(
        keycloak_sub=principal.sub,
        display_name=payload.display_name,
    )
    if updated.account_mode == "explorer":
        await PostgresDiscoveryRepository().rebuild_snapshot(updated.id)
    log_info(
        logger,
        "User display name updated",
        request_id=request_id_from(request),
        user_id=updated.id,
    )
    return await build_user_response(updated)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    request: Request,
    _: ProfileUpdater,
    principal: CurrentPrincipal,
    auth_service: AuthServiceDependency,
) -> None:
    """Delete the authenticated user's Keycloak account and local profile."""
    await auth_service.delete_account(principal_sub=principal.sub, request=request)
