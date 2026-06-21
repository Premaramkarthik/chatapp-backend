"""Central custom exception hierarchy for PariPath modules.

Keep domain and integration-specific exceptions here instead of defining ad hoc
classes inside service modules. Routers can translate these exceptions into HTTP
responses at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(eq=False)
class AppError(Exception):
    """Base class for all expected application exceptions."""

    message: str
    code: str = "app_error"
    context: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


class ConfigurationError(AppError):
    """Raised when application configuration is missing or invalid."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="configuration_error", context=context)


class DatabaseError(AppError):
    """Base exception for database/persistence failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="database_error", context=context)


class DatabaseConnectionError(DatabaseError):
    """Raised when the API cannot establish a database connection."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, context=context)
        self.code = "database_connection_error"


class MigrationError(DatabaseError):
    """Raised by migration tooling for invalid or failed migrations."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, context=context)
        self.code = "migration_error"


class AuthenticationError(AppError):
    """Base exception for authentication and identity failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "authentication_error",
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, context=context)


class SigninCallbackError(AuthenticationError):
    """Authentication failure during OAuth callback with a safe browser redirect target."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "authentication_error",
        post_signin_redirect_uri: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, context=context)
        self.post_signin_redirect_uri = post_signin_redirect_uri


class AuthorizationError(AppError):
    """Raised when an authenticated principal is not allowed to perform an action."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="authorization_error", context=context)


class IntegrationError(AppError):
    """Base exception for external service integration failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="integration_error", context=context)


class KeycloakIntegrationError(IntegrationError):
    """Raised for Keycloak-specific integration failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, context=context)
        self.code = "keycloak_integration_error"


class TypesenseIntegrationError(IntegrationError):
    """Raised for Typesense-specific integration failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, context=context)
        self.code = "typesense_integration_error"


class MatrixIntegrationError(IntegrationError):
    """Raised for Matrix Synapse integration failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, context=context)
        self.code = "matrix_integration_error"
