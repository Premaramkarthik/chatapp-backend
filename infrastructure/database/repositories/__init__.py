"""Repository adapter exports."""

from infrastructure.database.repositories.auth import PostgresAuthRepository
from infrastructure.database.repositories.conversations import PostgresConversationRepository
from infrastructure.database.repositories.discovery import PostgresDiscoveryRepository
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from infrastructure.database.repositories.travelers import PostgresTravelerRepository
from infrastructure.database.repositories.trips import PostgresTripRepository
from infrastructure.database.repositories.users import PostgresUserRepository

__all__ = [
    "PostgresAuthRepository",
    "PostgresConversationRepository",
    "PostgresDiscoveryRepository",
    "PostgresMatchingRepository",
    "PostgresTravelerRepository",
    "PostgresTripRepository",
    "PostgresUserRepository",
]
