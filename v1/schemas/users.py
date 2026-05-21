"""User API models."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserResponse(BaseModel):
    """Public shape returned for the current authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    keycloak_sub: str
    email: EmailStr | None = None
    display_name: str | None = None
    status: str
    account_mode: str = "messenger"
    email_verified: bool = False
    created_via: str = "email"
    onboarding_completed_at: datetime | None = None
    tos_accepted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AccountModeUpdateRequest(BaseModel):
    """Request body for changing business account mode."""

    account_mode: Literal["traveler", "messenger", "both"] = Field(
        ...,
        description="Business account mode. This is app state, not a Keycloak role.",
    )
