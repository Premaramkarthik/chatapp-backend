import sys
from pathlib import Path
from typing import Any

from loguru import logger


def setup_logger(
    log_file: str = "logs/backend.log",
    level: str = "INFO",
    *,
    json_logs: bool = False,
) -> None:
    """Configure loguru logger for console and rotating file output."""
    if "pytest" in sys.modules:
        return
    configured = getattr(setup_logger, "_configured", None)
    if (log_file, level, json_logs) == configured:
        return
    setup_logger._configured = (log_file, level, json_logs)
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.remove()

    console_format = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
    file_format = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}"

    logger.add(
        sys.stderr,
        format=console_format,
        level=level,
        colorize=True,
        serialize=json_logs,
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
        serialize=json_logs,
    )

    logger.info("logger_initialized log_file={} level={}", log_file, level)


def get_logger(name: str) -> Any:
    """Return a module-scoped logger instance.

    Args:
        name: Module name used for logger context.

    Returns:
        A loguru logger bound with module metadata.
    """
    return logger.bind(module=name)
