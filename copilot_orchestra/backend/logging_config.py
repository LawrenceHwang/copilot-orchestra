"""
Structured logging configuration using structlog.

Provides JSON logging in production and human-readable console output in debug mode.
Sensitive field names are automatically scrubbed from all log records.
"""

import logging
import sys
from typing import Any

import structlog

_SENSITIVE_KEYS = frozenset(
    {"api_key", "token", "secret", "password", "key", "authorization", "credential"}
)


def _scrub_sensitive(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Processor: remove any key that looks like a credential."""
    for key in list(event_dict.keys()):
        if any(s in key.lower() for s in _SENSITIVE_KEYS):
            event_dict[key] = "***REDACTED***"
    return event_dict


def configure_logging(log_level: str = "INFO", debug: bool = False) -> None:
    """
    Configure structlog and stdlib logging.

    Call once at application startup before any logging occurs.
    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _scrub_sensitive,
    ]

    if debug:
        # Human-readable console output for development
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # JSON output for production / log aggregation
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Quiet noisy third-party loggers
    for noisy in ("uvicorn.access", "httpx", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = "orchestra", **initial_values: Any) -> structlog.BoundLogger:
    """Return a bound structlog logger with optional initial context values."""
    return structlog.get_logger(name).bind(**initial_values)
