""" factory to create the specialist agents (graphs): the Recordability, Reportability and Hazard Control Workers """

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from ..aws import clients
from ..config import bounds
from ..prompts import PROMPTS
from ..tools.tools import TOOLSETS

MAX_SPECIALIST_TOOL_ROUNDS = bounds.max_specialist_tool_rounds

# the workers get_specialists builds; each one's brief is PROMPTS[name] and its tools TOOLSETS[name]
WORKERS = ("recordability", "reportability", "hazard_control")


class SpecialistState(TypedDict):
    """ a worker's private state. Deliberately tiny so each worker only has what it needs, and two running in parallel never mix transcripts """

    # input
    task: str
    incident: dict
    messages: Annotated[list[AnyMessage], add_messages]
    rounds: int

    # what the tools found, written by the tools themselves
    decisions: Annotated[dict[str, dict], operator.or_]     # keyed by rule id; the rules are deterministic, so a re-run just repeats
    retrieved: Annotated[dict[str, dict], operator.or_]

    # output: set by the propose tool once it accepts a proposal
    proposal: dict | None


def build_specialist(name: str, brief: str, tools: list[BaseTool], checkpointer: BaseCheckpointSaver | None = None):
    """ each specialist is just its own graph. this is a factory function that can build multiple types of specialists """

    model = clients.chat_model().bind_tools(tools)

    # node for prompting the model: it investigates with its tools, then proposes its finding through its propose tool
    def agent(state: SpecialistState) -> dict:
        history = list(state.get("messages") or [])
        seed: list = []
        # every run starts with its task; a thread that's reused (the Reviewer's) already has the brief
        if not state.get("rounds"):
            seed = ([] if history else [SystemMessage(brief)]) + [HumanMessage(state["task"])]
            history += seed

        reply = model.invoke(history)
        return {"messages": seed + [reply], "rounds": state.get("rounds", 0) + 1}

    # tool node
    def run_tools(state: SpecialistState, config) -> dict:
        return ToolNode(tools).invoke(state, config)

    # route after the model: it decides it's done by not asking for tools; the budget caps a model that never does
    def route(state: SpecialistState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            if state.get("rounds", 0) >= MAX_SPECIALIST_TOOL_ROUNDS:
                return END
            return "tools"
        return END

    # putting the graph together
    g = StateGraph(SpecialistState)
    g.add_node("agent", agent)
    g.add_node("tools", run_tools)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")

    # creating the specialist sub-graph and naming it for tracing; a checkpointer keeps its state on its own thread
    return g.compile(name=name, checkpointer=checkpointer)


# lazily loading the specialists so that just importing this module doesn't create them
_SPECIALISTS: dict | None = None


def get_specialists() -> dict:
    """ the compiled specialists, built once """

    global _SPECIALISTS
    if _SPECIALISTS is None:
        _SPECIALISTS = {name: build_specialist(name, PROMPTS[name], TOOLSETS[name]) for name in WORKERS}
    return _SPECIALISTS
