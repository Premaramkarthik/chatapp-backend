"""Central observability initialization."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.config.settings import settings
from core.logging.logger import get_logger, log_info
from core.observability.logging_context import observability_log_patcher
from core.observability.tracing import setup_tracing

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = get_logger(__name__)


def init_observability(app: FastAPI) -> None:
    """Configure tracing, logging patcher, and Prometheus instrumentator."""
    from loguru import logger as loguru_logger

    loguru_logger.configure(patcher=observability_log_patcher)

    if settings.observability.enabled:
        setup_tracing(app)

    if settings.observability.metrics_enabled:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator(
            should_group_status_codes=True,
            excluded_handlers=["/metrics", "/health/live", "/health/ready"],
        ).instrument(app)
        log_info(logger, "Prometheus FastAPI instrumentator enabled")
