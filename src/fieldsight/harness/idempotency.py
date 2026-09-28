""" idempotency keys for tool calls: the harness derives them from (session_id, tool_name, canonical arguments),
    never the model, so a retried call is recognised as the same call (section 9) """

import json
from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

# a fixed namespace, so the same call gets the same key in every process and on every run
NAMESPACE = uuid5(NAMESPACE_URL, "fieldsight:tool-call")


def _plain(value: Any) -> Any:
    """ JSON-ready values; sets become sorted lists, so their order can't change the key """

    if isinstance(value, BaseModel):
        return _plain(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, default=str))
    return value


def canonicalize(arguments: Mapping[str, Any] | BaseModel) -> str:
    """ the same arguments in any key order, at any depth, give the same text; a list keeps its order, since it means something """

    return json.dumps(_plain(arguments), sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def idempotency_key(session_id: str, tool_name: str, arguments: Mapping[str, Any] | BaseModel) -> UUID:
    """ the key a tool call is deduplicated by; uuid5, so a retry of the same call gets the same key.
        The dispatcher passes the model's tool-call args, never injected state """

    return uuid5(NAMESPACE, json.dumps([session_id, tool_name, canonicalize(arguments)], separators=(",", ":")))
