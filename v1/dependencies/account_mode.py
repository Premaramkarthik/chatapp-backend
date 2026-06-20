"""Business account_mode guards for role-specific routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status

from domains.users.user import User
from infrastructure.database.repositories.users import PostgresUserRepository
from v1.dependencies.auth import get_current_principal
from v1.schemas.principal import KeycloakPrincipal


def _require_account_mode(expected_mode: str) -> Callable:
    """Build a FastAPI dependency requiring a specific business account_mode."""

    async def dependency(
        principal: Annotated[KeycloakPrincipal, Depends(get_current_principal)],
    ) -> User:
        user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if user.account_mode != expected_mode:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires account_mode {expected_mode}",
            )
        return user

    return dependency


require_explorer_user = _require_account_mode("explorer")
require_connector_user = _require_account_mode("connector")

ExplorerUser = Annotated[User, Depends(require_explorer_user)]
ConnectorUser = Annotated[User, Depends(require_connector_user)]
