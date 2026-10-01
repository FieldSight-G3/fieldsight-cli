"""The Gateway offers API Gateway tools as {basePath, body}; callers pass each tool's own input and it goes in the body."""

import pytest

pytest.importorskip("mcp", reason="the Gateway client dependencies are installed only in the agent Runtime image")

from fieldsight.aws.gateway_client import api_tool

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class GatewayTool:
    """ stands in for a tool loaded from the Gateway: records what it was invoked with """

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "a Gateway tool"
        self.calls: list[dict] = []

    async def ainvoke(self, arguments: dict) -> str:
        self.calls.append(arguments)
        return "ok"


async def test_the_extraction_tool_sends_an_empty_json_body():
    gateway = GatewayTool("FieldSightReadTools___get_incident_extraction")

    assert await api_tool(gateway).ainvoke({}) == "ok"
    assert gateway.calls == [{"body": {}}]


async def test_the_similar_incidents_limit_goes_in_the_body():
    gateway = GatewayTool("FieldSightReadTools___find_similar_incidents")

    await api_tool(gateway).ainvoke({"limit": 2})
    assert gateway.calls == [{"body": {"limit": 2}}]


async def test_the_tool_keeps_its_gateway_name_and_never_forwards_an_incident_argument():
    gateway = GatewayTool("FieldSightReadTools___get_incident_extraction")
    tool = api_tool(gateway)

    assert tool.name == "FieldSightReadTools___get_incident_extraction"
    # the model chooses what, never whose (§9): an incident id the model adds never reaches the API
    await tool.ainvoke({"incident_id": "someone-elses"})
    assert gateway.calls == [{"body": {}}]


async def test_other_tools_are_left_unchanged():
    other = GatewayTool("SomeOtherTarget___search")

    assert api_tool(other) is other
