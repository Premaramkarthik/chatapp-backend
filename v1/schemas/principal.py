"""Authenticated principal models used across security boundaries."""

from pydantic import BaseModel, ConfigDict, EmailStr


class KeycloakPrincipal(BaseModel):
    """Authenticated user identity extracted from a Keycloak token."""

    model_config = ConfigDict(extra="allow")

    sub: str
    email: EmailStr | None = None
    email_verified: bool = False
    display_name: str | None = None
    preferred_username: str | None = None
    identity_provider: str | None = None
    roles: list[str] = []
    sid: str | None = None
    auth_time: int | None = None
