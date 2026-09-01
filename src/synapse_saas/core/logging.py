"""structlog configuration with tenant-aware context binding.

Logs are JSON in production (shippable to any collector); pretty console in development.
`bind_request_context` merges request-id/org/user into every subsequent log line.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from synapse_saas.core import context
from synapse_saas.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    level = logging.DEBUG if not settings.is_production else logging.INFO

    logging.basicConfig(format="%(message)s", level=level, stream=sys.stdout)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.dev.ConsoleRenderer() if not settings.is_production else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def bind_request_context() -> None:
    """Bind tenant/user/request-id into structlog contextvars for this request/task."""
    values: dict[str, Any] = {}
    if request_id := context.current_request_id():
        values["request_id"] = request_id
    if tenant := context.current_tenant():
        values["org_id"] = str(tenant.organization_id)
    if user := context.current_user():
        values["user_id"] = str(user.user_id)
    if values:
        structlog.contextvars.bind_contextvars(**values)
