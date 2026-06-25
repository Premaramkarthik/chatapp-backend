"""Matrix Synapse startup validation."""

from __future__ import annotations

from core.config.settings import settings
from core.logging.logger import get_logger, log_info
from infrastructure.matrix.admin import synapse_admin_client
from v1.utils.base import ConfigurationError, MatrixIntegrationError

logger = get_logger(__name__)


async def validate_matrix_startup() -> None:
    """Verify Synapse admin auth works before serving Matrix traffic."""
    if not settings.matrix.enabled:
        return

    try:
        await synapse_admin_client.login()
        await synapse_admin_client.verify_admin_access()
    except MatrixIntegrationError as exc:
        status_code = (exc.context or {}).get("status_code")
        if status_code == 403:
            raise ConfigurationError(
                "Matrix service admin logged in but lacks Synapse server-admin rights; "
                f"re-run synapse-bootstrap for {synapse_admin_client.service_admin_mxid} "
                "(see docs/matrix-chat-platform.md)",
                context={"detail": str(exc)},
            ) from exc
        if status_code == 429:
            raise ConfigurationError(
                "Synapse login rate limit exceeded during startup; wait a minute and "
                "restart the API, or restart synapse to pick up relaxed dev rc_login limits",
                context={"detail": str(exc)},
            ) from exc
        raise ConfigurationError(
            "Matrix service admin authentication failed; set "
            "MATRIX_SERVICE_ADMIN_USER/PASSWORD and run synapse-bootstrap "
            "(see docs/matrix-chat-platform.md)",
            context={"detail": str(exc)},
        ) from exc
    except Exception as exc:
        raise ConfigurationError(
            "Matrix service admin authentication failed; set "
            "MATRIX_SERVICE_ADMIN_USER/PASSWORD and run synapse-bootstrap "
            "(see docs/matrix-chat-platform.md)",
            context={"detail": str(exc)},
        ) from exc

    log_info(
        logger,
        "Matrix admin ready",
        service_admin_mxid=synapse_admin_client.service_admin_mxid,
    )
