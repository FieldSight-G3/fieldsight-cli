"""§13: an unreachable Gateway or ECS API disables only its tools; the turn continues and names what's gone."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp", reason="the Gateway client dependencies are installed only in the agent Runtime image")
httpx = pytest.importorskip("httpx")

from fieldsight import gateway_client
from fieldsight.gateway_client import (
    GATEWAY_TOOL_NAMES,
    UNREACHABLE,
    available_gateway_tools,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _gateway(tools=None, error=None, closed=None):
    """Stand-in for gateway_tools: yield these tools, or fail to connect with this error."""

    @asynccontextmanager
    async def fake(thread_id, *, caller_proof, region=None):
        if error is not None:
            raise error
        try:
            yield tools
        finally:
            if closed is not None:
                closed.append(True)

    return fake


@pytest.mark.parametrize("error", [
    httpx.ConnectError("connection refused"),
    RuntimeError("Set FIELDSIGHT_GATEWAY_URL to the FieldSight HTTPS MCP Gateway URL"),
    ExceptionGroup("task group", [httpx.ReadTimeout("read timed out")]),
])
async def test_unreachable_gateway_disables_its_tools_and_names_them(monkeypatch, error):
    monkeypatch.setattr(gateway_client, "gateway_tools", _gateway(error=error))

    async with available_gateway_tools("analyst:inc:recordability", caller_proof="proof") as toolset:
        assert toolset.tools == []
        assert toolset.unavailable == dict.fromkeys(GATEWAY_TOOL_NAMES, UNREACHABLE)


async def test_reachable_gateway_offers_every_tool(monkeypatch):
    tools = [SimpleNamespace(name=f"fieldsight-api___{name}") for name in GATEWAY_TOOL_NAMES]
    closed: list[bool] = []
    monkeypatch.setattr(gateway_client, "gateway_tools", _gateway(tools=tools, closed=closed))

    async with available_gateway_tools("analyst:inc:recordability", caller_proof="proof") as toolset:
        assert toolset.tools == tools
        assert toolset.unavailable == {}
        assert closed == []
    assert closed == [True]


async def test_a_tool_the_gateway_omits_is_named(monkeypatch):
    tools = [SimpleNamespace(name="fieldsight-api___get_incident_extraction")]
    monkeypatch.setattr(gateway_client, "gateway_tools", _gateway(tools=tools))

    async with available_gateway_tools("analyst:inc:recordability", caller_proof="proof") as toolset:
        assert toolset.tools == tools
        assert set(toolset.unavailable) == {"find_similar_incidents"}


async def test_errors_in_the_turn_are_not_swallowed(monkeypatch):
    closed: list[bool] = []
    monkeypatch.setattr(gateway_client, "gateway_tools", _gateway(tools=[], closed=closed))

    with pytest.raises(KeyError):
        async with available_gateway_tools("analyst:inc:recordability", caller_proof="proof"):
            raise KeyError("a bug in the turn")
    assert closed == [True]


@pytest.mark.parametrize(("thread_id", "proof"), [(" ", "proof"), ("analyst:inc:recordability", "")])
async def test_missing_thread_or_proof_is_a_caller_bug(monkeypatch, thread_id, proof):
    monkeypatch.setattr(gateway_client, "gateway_tools", _gateway(tools=[]))

    with pytest.raises(ValueError):
        async with available_gateway_tools(thread_id, caller_proof=proof):
            pass
