"""Users domain command and entities schemas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AccountMode(StrEnum):
    """Business profile mode for app behavior, not a Keycloak security role."""

    TRAVELER = "traveler"
    MESSENGER = "messenger"
    BOTH = "both"


class UserStatus(StrEnum):
    """Local account lifecycle state."""

    PENDING_VERIFICATION = "pending_verification"
    PENDING_PROFILE_SETUP = "pending_profile_setup"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class CreatedVia(StrEnum):
    """How the local account was created."""

    EMAIL = "email"
    GOOGLE = "google"
    APPLE = "apple"
    ADMIN = "admin"


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
    keycloak_sub: str | None
    email: str | None
    display_name: str | None
    status: str
    account_mode: str | None = None
    email_verified: bool = False
    created_via: str = CreatedVia.EMAIL.value
    last_verification_sent_at: datetime | str | None = None
    verification_send_count: int = 0
    onboarding_completed_at: datetime | str | None = None
    tos_accepted_at: datetime | str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None

    @classmethod
    def from_mapping(cls, data: dict) -> User:
        """Create a domain user from a persistence mapping."""
        return cls(
            id=str(data["id"]),
            keycloak_sub=None if data.get("keycloak_sub") is None else str(data["keycloak_sub"]),
            email=data.get("email"),
            display_name=data.get("display_name"),
            status=str(data.get("status", "active")),
            account_mode=data.get("account_mode"),
            email_verified=bool(data.get("email_verified", False)),
            created_via=str(data.get("created_via", CreatedVia.EMAIL.value)),
            last_verification_sent_at=data.get("last_verification_sent_at"),
            verification_send_count=int(data.get("verification_send_count", 0)),
            onboarding_completed_at=data.get("onboarding_completed_at"),
            tos_accepted_at=data.get("tos_accepted_at"),
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
            "account_mode": self.account_mode,
            "email_verified": self.email_verified,
            "created_via": self.created_via,
            "last_verification_sent_at": self.last_verification_sent_at,
            "verification_send_count": self.verification_send_count,
            "onboarding_completed_at": self.onboarding_completed_at,
            "tos_accepted_at": self.tos_accepted_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
