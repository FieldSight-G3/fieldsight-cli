""" the turn's Gateway reads: get_incident_extraction and find_similar_incidents, called once as the analyst at turn start

    The analyst's caller proof lives 60 seconds and only the analyst's own role can sign one, while a turn runs for
    minutes. So the reads happen first, while the proof is fresh, and the workers' tools serve what came back. A read
    that fails is named in `unavailable`, so the analyst is told which capability is gone and the rest continues.
"""

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from ..config import settings
from ..repository import SessionRepository

logger = logging.getLogger(__name__)

# the sessions row that binds a Gateway caller's thread to the one incident its reads may see
GATEWAY_PARTICIPANT = "gateway"
GATEWAY_UNAVAILABLE = "The AgentCore Gateway could not be reached"


class GatewayReads(BaseModel):
    """ what the Gateway returned this turn; a read that failed is None and its reason is in unavailable """

    extraction: dict[str, Any] | None = None
    similar: list[dict[str, Any]] | None = None
    unavailable: dict[str, str] = Field(default_factory=dict)  # tool name -> why, for the analyst


def gateway_configured() -> bool:
    return bool(os.environ.get("FIELDSIGHT_GATEWAY_URL") or os.environ.get("AGENTCORE_GATEWAY_FIELDSIGHTTOOLS_URL"))


def _response(content: Any) -> dict[str, Any]:
    """ the API's ToolResponse from an MCP tool result: a string or text blocks, maybe behind a Gateway error prefix """

    text = content if isinstance(content, str) else "".join(
        block.get("text", "") for block in content if isinstance(block, dict)) if isinstance(content, list) else ""
    start = text.find("{")
    if start < 0:
        raise ValueError("The Gateway returned no tool response")
    response, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(response, dict) or "ok" not in response:
        raise ValueError("The Gateway returned no tool response")
    return response


async def _read(thread_id: str, caller_proof: str, region: str) -> GatewayReads:
    import httpx
    from langchain_core.tools import ToolException
    from mcp.shared.exceptions import McpError

    from .gateway_client import GATEWAY_TOOL_NAMES, available_gateway_tools

    reads = GatewayReads()
    async with available_gateway_tools(thread_id, caller_proof=caller_proof, region=region) as toolset:
        reads.unavailable |= toolset.unavailable
        tools = {name: tool for tool in toolset.tools for name in GATEWAY_TOOL_NAMES
                 if tool.name == name or tool.name.endswith(f"___{name}")}
        for name, tool in tools.items():
            try:
                response = _response(await tool.ainvoke({}))
            # a tool error never fails the turn; it disables that capability
            except (ToolException, McpError, httpx.HTTPError, OSError, ValueError, ExceptionGroup) as error:
                logger.warning("gateway read failed: %s: %s", name, type(error).__name__)
                reads.unavailable[name] = GATEWAY_UNAVAILABLE
                continue
            if not response["ok"]:
                reads.unavailable[name] = (response.get("error") or {}).get("message") or GATEWAY_UNAVAILABLE
            elif name == "get_incident_extraction":
                reads.extraction = response["result"]
            else:
                reads.similar = response["result"]["items"]
    return reads


def read_through_gateway(analyst_id: UUID, incident_id: UUID, *, thread_id: str, caller_proof: str) -> GatewayReads:
    """ bind the proof's thread to this incident, then make both reads; the caller has already checked the grant """

    try:
        SessionRepository().get_or_create(thread_id, analyst_id, incident_id, GATEWAY_PARTICIPANT)
    except ValueError:
        # a reused runtime session already bound to another incident: its proof can't read this one
        reason = "This session is bound to a different incident; start a new session to read this one"
        return GatewayReads(unavailable={name: reason for name in ("get_incident_extraction", "find_similar_incidents")})
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_read(thread_id, caller_proof, settings.aws_region))
    # called from inside an event loop (an async host): run the reads on their own loop in a worker thread
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _read(thread_id, caller_proof, settings.aws_region)).result()
