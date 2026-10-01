""" factory to create the specialist agents (graphs): the Recordability, Reportability and Hazard Control Workers """

import operator
from typing import Annotated, TypedDict, get_args

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from ..aws import clients
from ..config import settings
from ..prompts import PROMPTS
from ..schemas.agents import Worker
from ..tools.tools import TOOLSETS

MAX_SPECIALIST_TOOL_ROUNDS = settings.bounds.max_specialist_tool_rounds

# the workers get_specialists builds; each one's brief is PROMPTS[name] and its tools TOOLSETS[name]
WORKERS = get_args(Worker)

# the result a tool call gets when its run stopped before it ran
NOT_RUN = "Not run: the previous run stopped before this tool call ran."

WIND_DOWN = ("Two tool rounds are left. Stop searching: call your propose tool (or submit_review) now with what you "
             "already have, citing chunks your searches returned. A run that ends without one fails.")


class SpecialistState(TypedDict):
    """ a worker's private state. Deliberately tiny so each worker only has what it needs, and two running in parallel never mix transcripts """

    # input
    task: str
    incident: dict
    gateway: dict | None    # this turn's Gateway reads (aws/gateway_reads); None when no Gateway is configured
    messages: Annotated[list[AnyMessage], add_messages]
    rounds: int
    run_start: int          # where this run's messages begin on a reused thread; earlier runs stay stored, unsent

    # what the tools found, written by the tools themselves
    decisions: Annotated[dict[str, dict], operator.or_]     # keyed by rule id; the rules are deterministic, so a re-run just repeats
    retrieved: Annotated[dict[str, dict], operator.or_]

    # output: set by the propose tool once it accepts a proposal
    proposal: dict | None


def unanswered(history: list[AnyMessage]) -> list[ToolMessage]:
    """ a "not run" result for each tool call a reused thread ends on

        The round cap or the recursion limit can stop a run after the model asked for tools and before they ran.
        Bedrock refuses a toolUse with no toolResult after it, so the thread's next run would fail without these.
    """

    last = history[-1] if history else None
    if not (isinstance(last, AIMessage) and last.tool_calls):
        return []
    return [ToolMessage(NOT_RUN, tool_call_id=call["id"]) for call in last.tool_calls]


def build_specialist(name: str, brief: str, tools: list[BaseTool], checkpointer: BaseCheckpointSaver | None = None):
    """ each specialist is just its own graph. this is a factory function that can build multiple types of specialists """

    model = clients.chat_model().bind_tools(tools)

    # node for prompting the model: it investigates with its tools, then proposes its finding through its propose tool
    def agent(state: SpecialistState) -> dict:
        messages = list(state.get("messages") or [])
        # a reused thread's last run can end on tool calls the cap stopped; they're closed on the thread first, so
        # the stored thread stays valid for Bedrock, and this run starts after them
        closing = unanswered(messages) if not state.get("rounds") else []
        # a reused thread (the Reviewer's) keeps every earlier run, but the model sees only this one: replaying them
        # all grew each call past 30K tokens, and the task already holds everything this run judges
        start = len(messages) + len(closing) if not state.get("rounds") else state.get("run_start", 0)
        # the brief goes in fresh on every call, never into the thread: a reused thread would otherwise keep the
        # brief it was first run with, and a changed prompt would never reach it
        history = [message for message in messages[start:] if not isinstance(message, SystemMessage)]
        seed: list = []
        # every run starts with its task
        if not state.get("rounds"):
            history.append(HumanMessage(state["task"]))
            seed = closing + history[-1:]
        # the cap drops the last round's tool calls, so warn while two rounds can still run: one to propose, one to fix it
        elif state["rounds"] == MAX_SPECIALIST_TOOL_ROUNDS - 3:
            seed = [HumanMessage(WIND_DOWN)]
            history += seed

        reply = model.invoke([SystemMessage(brief)] + history)
        return {"messages": seed + [reply], "rounds": state.get("rounds", 0) + 1, "run_start": start}

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
