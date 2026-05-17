"""Users domain command and entities schemas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class BootstrapUserCommand:
    """Command for creating or returning a local user for an identity subject."""

    keycloak_sub: str
    email: str | None
    display_name: str | None


@dataclass(frozen=True, slots=True)
class User:
    """Local application user linked to an external identity subject."""

    id: str
    keycloak_sub: str
    email: str | None
    display_name: str | None
    status: str
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None

    @classmethod
    def from_mapping(cls, data: dict) -> User:
        """Create a domain user from a persistence mapping."""
        return cls(
            id=str(data["id"]),
            keycloak_sub=str(data["keycloak_sub"]),
            email=data.get("email"),
            display_name=data.get("display_name"),
            status=str(data.get("status", "active")),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> dict:
        """Return a serializable representation for API response mapping."""
        return {
            "id": self.id,
            "keycloak_sub": self.keycloak_sub,
            "email": self.email,
            "display_name": self.display_name,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
