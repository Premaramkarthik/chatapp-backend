"""Default Keycloak capability role helpers."""

from __future__ import annotations

from core.config.settings import settings
from domains.auth.keycloak_client import KeycloakAuthClient, keycloak_auth_client
from domains.auth.models import TokenSet
from infrastructure.keycloak.adapter import keycloak_verifier
from v1.schemas.principal import KeycloakPrincipal


def missing_default_capabilities(roles: list[str]) -> list[str]:
    """Return configured signup capabilities absent from the principal roles."""
    if "admin" in roles:
        return []
    present = set(roles)
    return [role for role in settings.auth.default_signup_roles if role not in present]


async def ensure_default_capabilities(
    *,
    keycloak_sub: str,
    roles: list[str],
    keycloak: KeycloakAuthClient | None = None,
) -> bool:
    """Assign default client roles when the principal is missing baseline capabilities."""
    missing = missing_default_capabilities(roles)
    if not missing:
        return False
    client = keycloak or keycloak_auth_client
    await client.assign_default_client_roles(user_id=keycloak_sub)
    return True


async def refresh_token_set_if_needed(
    *,
    keycloak_sub: str,
    roles: list[str],
    token_set: TokenSet,
    keycloak: KeycloakAuthClient | None = None,
) -> tuple[TokenSet, KeycloakPrincipal]:
    """Backfill missing roles and refresh tokens so the access token includes them."""
    client = keycloak or keycloak_auth_client
    if not await ensure_default_capabilities(
        keycloak_sub=keycloak_sub,
        roles=roles,
        keycloak=client,
    ):
        principal = await keycloak_verifier.verify_token(token_set.access_token)
        return token_set, principal

    if not token_set.refresh_token:
        principal = await keycloak_verifier.verify_token(token_set.access_token)
        return token_set, principal

    refreshed = await client.refresh(refresh_token=token_set.refresh_token)
    principal = await keycloak_verifier.verify_token(refreshed.access_token)
    return refreshed, principal
