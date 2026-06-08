"""Structured domain event names for auth and Keycloak operations."""

from __future__ import annotations

from typing import Any

from core.logging.logger import get_logger

logger = get_logger(__name__)

AUTH_SIGNUP_STARTED = "AUTH_SIGNUP_STARTED"
AUTH_SIGNUP_SUCCESS = "AUTH_SIGNUP_SUCCESS"
AUTH_SIGNUP_FAILED = "AUTH_SIGNUP_FAILED"
KEYCLOAK_USER_CREATED = "KEYCLOAK_USER_CREATED"
KEYCLOAK_USER_UPDATED = "KEYCLOAK_USER_UPDATED"
KEYCLOAK_USER_DELETED = "KEYCLOAK_USER_DELETED"
VERIFICATION_EMAIL_SENT = "VERIFICATION_EMAIL_SENT"
PASSWORD_RESET_TRIGGERED = "PASSWORD_RESET_TRIGGERED"
JWT_VALIDATION_FAILED = "JWT_VALIDATION_FAILED"
CONFIGURATION_LOADED = "CONFIGURATION_LOADED"


def log_domain_event(event: str, **fields: Any) -> None:
    """Emit a structured domain event log line."""
    if fields:
        parts = " ".join(f"{key}=%s" for key in fields)
        logger.info("domain_event event=%s " + parts, event, *fields.values())
    else:
        logger.info("domain_event event=%s", event)
