"""Current-user routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from v1.dependencies.auth import get_current_principal
from v1.dependencies.container import get_bootstrap_user_use_case
from v1.models.user import BootstrapUserCommand
from v1.schemas.principal import KeycloakPrincipal
from v1.schemas.users import UserResponse
from v1.services.users.bootstrap_user import BootstrapUser

router = APIRouter(prefix="/v1", tags=["users"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
BootstrapUserUseCase = Annotated[BootstrapUser, Depends(get_bootstrap_user_use_case)]


@router.get("/me", response_model=UserResponse)
async def me(principal: CurrentPrincipal, bootstrap_user: BootstrapUserUseCase) -> dict:
    """Return the current local chatapp user, creating it on first login."""
    display_name = principal.display_name or principal.preferred_username
    user = await bootstrap_user.execute(
        BootstrapUserCommand(
            keycloak_sub=principal.sub,
            email=principal.email,
            display_name=display_name,
        )
    )
    return user.to_dict()
