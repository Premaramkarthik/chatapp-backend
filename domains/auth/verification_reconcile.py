"""Reconcile pending_verification users verified in Keycloak but not yet activated locally."""

from __future__ import annotations

import asyncio

from core.config.settings import settings
from core.logging.logger import get_logger
from core.observability.instrumentation import observe_service
from core.observability.prometheus_metrics import (
    BACKGROUND_JOB_FAILURES_TOTAL,
    BACKGROUND_JOB_RUNS_TOTAL,
    PENDING_VERIFICATIONS,
    VERIFICATION_SUCCESS_TOTAL,
)
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
    pending_rows = await fetch(
        "SELECT COUNT(*) AS count FROM users WHERE status = 'pending_verification'",
    )
    if pending_rows:
        PENDING_VERIFICATIONS.set(int(pending_rows[0]["count"]))

    rows = await fetch(
        """
        SELECT id, email, keycloak_sub
        FROM users
        WHERE status = 'pending_verification'
          AND keycloak_sub IS NOT NULL
          AND display_name IS NOT NULL
          AND account_mode IS NOT NULL
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
            logger.warning(
                "verification_reconcile_keycloak_lookup_failed user_id={} keycloak_sub={} "
                "error_type={}",
                user_id,
                keycloak_sub,
                type(exc).__name__,
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
            logger.warning(
                "verification_reconcile_activation_failed user_id={} keycloak_sub={}",
                user_id,
                keycloak_sub,
            )
            continue

        await auth_repository.write_outbox_event(
            event_type="signup.verified",
            aggregate_type="user",
            aggregate_id=activated.id,
            payload={"source": "reconciliation"},
        )
        VERIFICATION_SUCCESS_TOTAL.labels(source="reconcile").inc()
        activated_count += 1
        logger.info(
            "verification_reconcile_activation_succeeded user_id={} keycloak_sub={} status={}",
            activated.id,
            keycloak_sub,
            activated.status,
        )

    return activated_count


async def run_verification_reconcile_loop(
    stop_event: asyncio.Event,
    *,
    interval_sec: float | None = None,
) -> None:
    """Periodically reconcile Keycloak-verified users stuck in pending_verification."""
    from opentelemetry import trace

    tracer = trace.get_tracer(__name__)
    delay = interval_sec or settings.auth.verification_reconcile_interval_sec
    while not stop_event.is_set():
        with tracer.start_as_current_span("background.verification_reconcile"):
            try:
                BACKGROUND_JOB_RUNS_TOTAL.labels(job="verification_reconcile").inc()
                activated = await reconcile_pending_verifications_once(batch_size=None)
                if activated:
                    logger.info(
                        "verification_reconcile_batch_complete activated_count={}",
                        activated,
                    )
            except Exception as exc:
                BACKGROUND_JOB_FAILURES_TOTAL.labels(job="verification_reconcile").inc()
                logger.warning(
                    "verification_reconcile_loop_error error_type={}",
                    type(exc).__name__,
                )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except TimeoutError:
            continue
