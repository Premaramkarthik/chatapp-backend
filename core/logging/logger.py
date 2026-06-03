import sys
from pathlib import Path
from typing import Any

from loguru import logger

from core.config.settings import settings
from core.observability.logging_context import observability_log_patcher


def setup_logger(
    log_file: str = "logs/backend.log",
    level: str = "INFO",
    *,
    json_logs: bool | None = None,
) -> None:
    """Configure loguru logger for console and rotating file output."""
    if "pytest" in sys.modules:
        return
    resolved_json = json_logs if json_logs is not None else settings.logging.json_logs
    configured = getattr(setup_logger, "_configured", None)
    if (log_file, level, resolved_json) == configured:
        return
    setup_logger._configured = (log_file, level, resolved_json)
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.configure(patcher=observability_log_patcher)

    console_format = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
    file_format = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}"

    logger.add(
        sys.stderr,
        format=console_format,
        level=level,
        colorize=True,
        serialize=resolved_json,
    )

    logger.add(
        log_file,
        rotation="100 MB",
        retention="30 days",
        level=level,
        format=file_format,
        encoding="utf-8",
        mode="a",
        backtrace=True,
        diagnose=True,
        serialize=resolved_json,
    )

    logger.info("logger_initialized log_file={} level={} json={}", log_file, level, resolved_json)


def get_logger(name: str) -> Any:
    """Return a module-scoped logger instance.

    Args:
        name: Module name used for logger context.

    Returns:
        A loguru logger bound with module metadata.
    """
    return logger.bind(module=name)
