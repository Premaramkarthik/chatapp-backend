import sys
from pathlib import Path
from typing import Any

from loguru import logger

from core.observability.logging_context import observability_log_patcher

LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[request_id]} | "
    "{extra[logger_name]}:{function}:{line} | {message}"
)


def setup_logger(
    log_file: str = "logs/backend.log",
    level: str = "INFO",
) -> None:
    """Configure loguru for app logs; leave uvicorn on its native handlers/format."""
    if "pytest" in sys.modules:
        return

    configured = getattr(setup_logger, "_configured", None)
    config_key = (log_file, level)
    if config_key == configured:
        return
    setup_logger._configured = config_key

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.configure(
        patcher=observability_log_patcher,
        extra={"request_id": "", "logger_name": ""},
    )

    logger.add(
        sys.stderr,
        format=LOG_FORMAT,
        level=level,
        colorize=True,
        serialize=False,
    )

    logger.add(
        log_file,
        rotation="100 MB",
        retention="30 days",
        level=level,
        format=LOG_FORMAT,
        encoding="utf-8",
        mode="a",
        backtrace=True,
        diagnose=True,
        serialize=False,
    )

    logger.info(
        "logger_initialized log_file={} level={}",
        log_file,
        level,
    )


def get_logger(name: str) -> Any:
    """Return a module-scoped logger instance.

    Args:
        name: Module name used for logger context.

    Returns:
        A loguru logger bound with module metadata.
    """
    return logger.bind(module=name, logger_name=name)
