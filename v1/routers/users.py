"""Current-user routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from v1.database.repositories import PostgresUserRepository
from v1.dependencies.auth import get_current_principal, require_capability
from v1.dependencies.container import get_bootstrap_user_use_case
from v1.models.user import BootstrapUserCommand
from v1.schemas.principal import KeycloakPrincipal
from v1.schemas.users import AccountModeUpdateRequest, UserResponse
from v1.services.users.bootstrap_user import BootstrapUser

router = APIRouter(prefix="/v1", tags=["users"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
BootstrapUserUseCase = Annotated[BootstrapUser, Depends(get_bootstrap_user_use_case)]
ProfileUpdater = Annotated[KeycloakPrincipal, Depends(require_capability("profile:update"))]


@router.get("/me", response_model=UserResponse)
async def me(principal: CurrentPrincipal, bootstrap_user: BootstrapUserUseCase) -> dict:
    """Return the current local chatapp user, creating it on first signin."""
    display_name = principal.display_name or principal.preferred_username
    user = await bootstrap_user.execute(
        BootstrapUserCommand(
            keycloak_sub=principal.sub,
            email=principal.email,
            display_name=display_name,
        )
    )
    return user.to_dict()


@router.patch("/me/account-mode", response_model=UserResponse)
async def update_account_mode(
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
        )
    )
    user = await PostgresUserRepository().update_account_mode(
        keycloak_sub=principal.sub,
        account_mode=payload.account_mode,
    )
    return user.to_dict()
