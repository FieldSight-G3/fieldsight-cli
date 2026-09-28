"""Structured JSON logs that carry the turn's correlation id from a contextvar."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar
from uuid import uuid4

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# an inbound id is trusted only if it looks like one; anything else gets a fresh id
_VALID_ID = re.compile(r"[A-Za-z0-9._:-]{1,64}")

P = ParamSpec("P")
R = TypeVar("R")


def valid_correlation_id(value: str | None) -> str | None:
    return value if value and _VALID_ID.fullmatch(value) else None


@contextmanager
def correlated(value: str | None = None) -> Iterator[str]:
    """Bind a correlation id (a fresh one if none is given) for everything inside the block."""
    token = correlation_id.set(valid_correlation_id(value) or str(uuid4()))
    try:
        yield correlation_id.get() or ""
    finally:
        correlation_id.reset(token)


def with_correlation_id(func: Callable[P, R]) -> Callable[P, R]:
    """Run under the caller's correlation id, or a fresh one when the caller has none."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        if correlation_id.get() is not None:
            return func(*args, **kwargs)
        with correlated():
            return func(*args, **kwargs)

    return wrapper


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": getattr(record, "correlation_id", None) or correlation_id.get() or "-",
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: int | str = logging.INFO) -> None:
    """One JSON handler on the root logger; calling it again changes nothing."""
    root = logging.getLogger()
    root.setLevel(level)
    if any(isinstance(handler.formatter, JsonFormatter) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationFilter())
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
