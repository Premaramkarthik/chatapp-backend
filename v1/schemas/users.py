"""User API models."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserResponse(BaseModel):
    """Public shape returned for the current authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    keycloak_sub: str
    email: EmailStr | None = None
    display_name: str | None = None
    status: str
    account_mode: str | None = None
    email_verified: bool = False
    created_via: str = "email"
    onboarding_completed_at: datetime | None = None
    tos_accepted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    onboarding_complete: bool = False
    profile_exists: bool = False


class AccountModeUpdateRequest(BaseModel):
    """Request body for changing business account mode."""

    account_mode: Literal["explorer", "connector"] = Field(
        ...,
        description="Business account mode. This is app state, not a Keycloak role.",
    )


class DisplayNameUpdateRequest(BaseModel):
    """Request body for updating the user's display name."""

    display_name: str = Field(..., min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 2:
            msg = "Display name must be at least 2 characters"
            raise ValueError(msg)
        return normalized
