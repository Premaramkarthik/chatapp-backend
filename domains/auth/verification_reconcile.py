"""Reconcile pending_verification users verified in Keycloak but not yet activated locally."""

from __future__ import annotations

import asyncio

from core.config.settings import settings
from core.logging.logger import get_logger, log_info, log_warning
from core.observability.instrumentation import observe_service
from domains.auth.keycloak_client import keycloak_auth_client
from infrastructure.database.connection import fetch
from infrastructure.database.repositories.auth import PostgresAuthRepository
from infrastructure.database.repositories.users import PostgresUserRepository

logger = get_logger(__name__)


@observe_service("verification_reconcile")
async def reconcile_pending_verifications_once(*, batch_size: int | None = None) -> int:
    """Activate pending users whose Keycloak account is already email-verified.

    Returns the number of users activated in this batch.
    """
    limit = batch_size or settings.auth.verification_reconcile_batch_size

    rows = await fetch(
        """
        SELECT id, email, keycloak_sub
        FROM users
        WHERE status = 'pending_verification'
          AND keycloak_sub IS NOT NULL
        ORDER BY created_at ASC
        LIMIT $1
        """,
        limit,
    )
    if not rows:
        return 0

    user_repository = PostgresUserRepository()
    auth_repository = PostgresAuthRepository()
    activated_count = 0

    for row in rows:
        keycloak_sub = str(row["keycloak_sub"])
        email = str(row["email"])
        user_id = str(row["id"])
        try:
            email_verified = await keycloak_auth_client.get_user_email_verified(
                user_id=keycloak_sub,
            )
        except Exception as exc:
            log_warning(
                logger,
                "Email verification reconcile could not look up user in Keycloak",
                user_id=user_id,
                keycloak_sub=keycloak_sub,
                error_type=type(exc).__name__,
            )
            continue

        if not email_verified:
            continue

        activated = await user_repository.activate_after_verified_signin(
            keycloak_sub=keycloak_sub,
            email=email,
            email_verified=True,
        )
        if activated is None:
            log_warning(
                logger,
                "Email verification reconcile could not activate user locally",
                user_id=user_id,
                keycloak_sub=keycloak_sub,
            )
            continue

        await auth_repository.write_outbox_event(
            event_type="signup.verified",
            aggregate_type="user",
            aggregate_id=activated.id,
            payload={"source": "reconciliation"},
        )
        activated_count += 1
        log_info(
            logger,
            "Email verification reconcile activated user after Keycloak verification",
            user_id=activated.id,
            keycloak_sub=keycloak_sub,
            status=activated.status,
        )

    return activated_count


async def run_verification_reconcile_loop(
    stop_event: asyncio.Event,
    *,
    interval_sec: float | None = None,
) -> None:
    """Periodically reconcile Keycloak-verified users stuck in pending_verification."""

    delay = interval_sec or settings.auth.verification_reconcile_interval_sec
    while not stop_event.is_set():
        try:
            activated = await reconcile_pending_verifications_once(batch_size=None)
            if activated:
                log_info(
                    logger,
                    "Email verification reconcile batch completed",
                    activated_count=activated,
                )
        except Exception as exc:
            log_warning(
                logger,
                "Email verification reconcile background loop failed",
                error_type=type(exc).__name__,
            )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except TimeoutError:
            continue
