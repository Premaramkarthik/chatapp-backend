"""Current-user routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from domains.auth import AuthService
from domains.users.bootstrap import BootstrapUser
from domains.users.user import BootstrapUserCommand
from infrastructure.database.repositories import PostgresUserRepository
from v1.dependencies.auth import get_current_principal, require_capability
from v1.dependencies.container import get_auth_service, get_bootstrap_user_use_case
from v1.schemas.principal import KeycloakPrincipal
from v1.schemas.users import AccountModeUpdateRequest, UserResponse
from v1.utils.request_context import request_id_from

router = APIRouter(prefix="/v1/users", tags=["users"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
BootstrapUserUseCase = Annotated[BootstrapUser, Depends(get_bootstrap_user_use_case)]
AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
ProfileUpdater = Annotated[KeycloakPrincipal, Depends(require_capability("profile:update"))]


@router.patch("/account-mode", response_model=UserResponse)
async def update_account_mode(
    request: Request,
    payload: AccountModeUpdateRequest,
    _: ProfileUpdater,
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
    return user.to_dict()


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    request: Request,
    _: ProfileUpdater,
    principal: CurrentPrincipal,
    auth_service: AuthServiceDependency,
) -> None:
    """Delete the authenticated user's Keycloak account and local profile."""
    await auth_service.delete_account(principal_sub=principal.sub, request=request)
