"""Harness-side idempotency keys: the same call in the same session always gets the same key.

The key is derived from (session_id, tool_name, canonicalized arguments), never supplied by a
model (section 9). Canonicalization is order-independent for mapping keys and set members;
list order is meaningful and kept. The key is a uuid5, so a retry of the same call gets the same key.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

# a fixed namespace, so the same call gets the same key in every process and on every run
NAMESPACE = uuid5(NAMESPACE_URL, "fieldsight:tool-call")


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Argument names must be strings")
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        # a set has no order, so sort its members by their canonical text
        return sorted((_normalize(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, (float, Decimal)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Arguments must be finite numbers")
        # 2 and 2.0 are the same argument
        return int(number) if number.is_integer() else number
    if isinstance(value, (UUID, datetime, date)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    raise TypeError(f"Cannot canonicalize {type(value).__name__}")


def canonicalize(arguments: Mapping[str, Any] | BaseModel) -> str:
    """One stable JSON text for a set of arguments, whatever order their keys arrived in."""
    return json.dumps(_normalize(arguments), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def idempotency_key(session_id: str, tool_name: str, arguments: Mapping[str, Any] | BaseModel) -> UUID:
    """The key a tool call is deduplicated by; the dispatcher passes the model's tool-call args, never injected state."""
    if not session_id.strip() or not tool_name.strip():
        raise ValueError("A session id and tool name are required")
    # the unit separator keeps ("a", "b:c") and ("a:b", "c") apart
    return uuid5(NAMESPACE, "\x1f".join((session_id, tool_name, canonicalize(arguments))))
