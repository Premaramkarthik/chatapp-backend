"""User API models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class UserResponse(BaseModel):
    """Public shape returned for the current authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    keycloak_sub: str
    email: EmailStr | None = None
    display_name: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
