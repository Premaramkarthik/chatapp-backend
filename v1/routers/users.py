"""Current-user routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.logging.logger import get_logger, log_info
from domains.auth import AuthService
from domains.users.bootstrap import BootstrapUser
from domains.users.user import BootstrapUserCommand, User
from infrastructure.database.repositories import PostgresUserRepository
from infrastructure.database.repositories.connection_screens import ConnectionScreenRepository
from infrastructure.database.repositories.discovery import PostgresDiscoveryRepository
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from v1.dependencies.auth import get_current_principal, require_capability
from v1.dependencies.container import get_auth_service, get_bootstrap_user_use_case
from v1.schemas.principal import KeycloakPrincipal
from v1.schemas.users import (
    AccountModeUpdateRequest,
    DisplayNameUpdateRequest,
    PublicUserProfileResponse,
    UserResponse,
)
from v1.utils.request_context import request_id_from
from v1.utils.user_session import build_user_response

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/users", tags=["users"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
BootstrapUserUseCase = Annotated[BootstrapUser, Depends(get_bootstrap_user_use_case)]
AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
ProfileUpdater = Annotated[KeycloakPrincipal, Depends(require_capability("profile:update"))]


async def _profile_viewer(
    principal: Annotated[KeycloakPrincipal, Depends(require_capability("profile:update"))],
) -> User:
    """Resolve the local user row for profile lookup routes."""
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


ProfileViewer = Annotated[User, Depends(_profile_viewer)]


async def _build_public_profile(viewer_id: str, target_user_id: str) -> PublicUserProfileResponse:
    """Load a public profile card respecting blocks and discoverability."""
    if viewer_id == target_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use account settings for your own profile",
        )

    target = await PostgresUserRepository().get_by_id(target_user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if await PostgresMatchingRepository().is_blocked(viewer_id, target_user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if target.account_mode == "explorer":
        rows = await PostgresDiscoveryRepository().fetch_public_by_ids([target_user_id])
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Profile not available"
            )
        row = rows[0]
        visibility = row.get("visibility") or "discoverable"
        if visibility == "hidden":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Profile not available"
            )
        return PublicUserProfileResponse(
            user_id=UUID(str(row["user_id"])),
            display_name=row.get("display_name"),
            account_mode="explorer",
            avatar_url=row.get("avatar_url"),
            headline=row.get("headline"),
            home_label=row.get("home_label"),
            destination_country_iso=row.get("destination_country_iso"),
            destination_city_name=row.get("destination_city_name"),
            current_country_iso=row.get("current_country_iso"),
            languages=list(row.get("languages") or []),
            interests=list(row.get("interests") or []),
            connection_availability=row.get("connection_availability") or "open",
            last_active_at=row.get("last_active_at"),
        )

    peer = (await ConnectionScreenRepository().fetch_peers([target_user_id])).get(target_user_id)
    if peer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not available")
    return PublicUserProfileResponse(
        user_id=UUID(str(peer["user_id"])),
        display_name=peer.get("display_name"),
        account_mode=peer.get("account_mode") or "connector",
        avatar_url=peer.get("avatar_url"),
        headline=peer.get("headline"),
        home_label=peer.get("home_label"),
        destination_country_iso=peer.get("destination_country_iso"),
        destination_city_name=peer.get("destination_city_name"),
        languages=list(peer.get("languages") or []),
        interests=[],
        connection_availability="open",
        last_active_at=peer.get("last_active_at"),
    )


@router.get("/{user_id}/public-profile", response_model=PublicUserProfileResponse)
async def get_public_profile(user_id: UUID, viewer: ProfileViewer) -> PublicUserProfileResponse:
    """Return a public profile card for another user."""
    return await _build_public_profile(viewer.id, str(user_id))


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
