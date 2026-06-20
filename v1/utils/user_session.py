"""Build enriched user payloads for session and auth responses."""

from __future__ import annotations

from domains.users.user import User
from infrastructure.database.repositories.connectors import PostgresConnectorRepository
from infrastructure.database.repositories.explorers import PostgresExplorerRepository


async def build_user_response(user: User) -> dict:
    """Return user dict with onboarding_complete and mode-specific profile_exists."""
    profile_exists = await _role_profile_exists(user.id, user.account_mode)
    payload = user.to_dict()
    payload["onboarding_complete"] = user.onboarding_completed_at is not None
    payload["profile_exists"] = profile_exists
    return payload


async def _role_profile_exists(user_id: str, account_mode: str | None) -> bool:
    """Return True when the profile row for the active account_mode exists."""
    repo = PostgresExplorerRepository()
    if account_mode == "explorer":
        return (await repo.get_explorer_profile(user_id)) is not None
    if account_mode == "connector":
        return (await PostgresConnectorRepository().get_connector_profile(user_id)) is not None
    return False
