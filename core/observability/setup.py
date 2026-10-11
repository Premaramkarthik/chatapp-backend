"""Initialize structured logging without external telemetry exporters."""

from loguru import logger

from core.observability.logging_context import observability_log_patcher


def init_observability(app) -> None:
    logger.configure(patcher=observability_log_patcher)
