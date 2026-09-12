"""Logging configuration for BGAnalyzer."""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

import structlog
from structlog.stdlib import ProcessorFormatter


def setup_logging() -> None:
    """Configure structured logging for the application."""
    log_dir = (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        / "bganalyzer"
        / "logs"
    )
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_file = log_dir / "bganalyzer.log"

    shared_processors = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    log_file.chmod(0o600)
    file_formatter = ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    file_handler.setFormatter(file_formatter)

    console_handler = logging.StreamHandler(sys.stderr)
    console_formatter = ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=False),
        foreign_pre_chain=shared_processors,
    )
    console_handler.setFormatter(console_formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = [file_handler, console_handler]

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("PySide6").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)
