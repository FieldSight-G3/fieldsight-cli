""" factory to create the specialist agents (graphs): the Recordability and Reportability Workers """

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from ..aws import clients
from ..prompts import PROMPTS
from ..tools.tools import RECORDABILITY_TOOLS, REPORTABILITY_TOOLS

MAX_SPECIALIST_TOOL_ROUNDS = 10


class SpecialistState(TypedDict):
    """ a specialist's private state, so running two in parallel never mixes their transcripts """

    # input
    worker: str
    task: str
    incident: dict
    messages: Annotated[list[AnyMessage], add_messages]
    rounds: int

    # what the tools found, written by the tools themselves
    decisions: Annotated[list[dict], operator.add]
    retrieved: Annotated[list[str], operator.add]

    # output: set by the propose tool once it accepts a proposal, which ends the loop
    proposal: dict | None


def build_specialist(name: str, tools: list[BaseTool]):
    """ each specialist is just its own graph; this factory builds any of them """

    system = PROMPTS[name]
    model = clients.chat_model().bind_tools(tools)

    # node for prompting the model: it chooses which tool to call, and when it's done
    def agent(state: SpecialistState) -> dict:
        history = list(state.get("messages") or [])
        seed: list = []
        if not history:
            seed = [SystemMessage(system), HumanMessage(state["task"])]
            history = seed

        reply = model.invoke(history)
        return {"messages": seed + [reply], "rounds": state.get("rounds", 0) + 1}

    # tool node
    def run_tools(state: SpecialistState, config) -> dict:
        return ToolNode(tools).invoke(state, config)

    # route after the model, in plain Python: back to the tools while it asks for them and the budget allows
    def route_after_agent(state: SpecialistState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            if state.get("rounds", 0) >= MAX_SPECIALIST_TOOL_ROUNDS:
                return END
            return "tools"
        return END

    # route after the tools: an accepted proposal is the structured event that ends the loop
    def route_after_tools(state: SpecialistState) -> str:
        return END if state.get("proposal") else "agent"

    # putting the graph together
    g = StateGraph(SpecialistState)
    g.add_node("agent", agent)
    g.add_node("tools", run_tools)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
    g.add_conditional_edges("tools", route_after_tools, {"agent": "agent", END: END})

    # creating the specialist sub-graph and naming it for tracing
    return g.compile(name=name)


_TOOLSETS = {
    "recordability": RECORDABILITY_TOOLS,
    "reportability": REPORTABILITY_TOOLS,
}

# lazily loading the specialists so that just importing this module doesn't create them
_SPECIALISTS: dict | None = None


def get_specialists() -> dict:
    """ the compiled specialists, built once """

    global _SPECIALISTS
    if _SPECIALISTS is None:
        _SPECIALISTS = {name: build_specialist(name, tools) for name, tools in _TOOLSETS.items()}
    return _SPECIALISTS
