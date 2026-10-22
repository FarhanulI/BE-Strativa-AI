from __future__ import annotations

import logging
import re
from typing import Any

import structlog

_SENSITIVE_KEY = re.compile(
    r"password|token|secret|authorization|credential|api[_-]?key|private[_-]?key|database_url|redis_url",
    re.I,
)


def redact_sensitive_values(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact(nested)
                for key, nested in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return redact(event_dict)


def configure_logging(*, level: str = "INFO") -> None:
    logging.basicConfig(level=level.upper(), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            redact_sensitive_values,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )