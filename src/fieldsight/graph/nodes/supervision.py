""" nodes for the Coordinator and the worker sub-graphs it dispatches """

from langgraph.errors import GraphRecursionError

from ...config import settings
from ...prompts import HAZARD_CONTROL_GOAL, RECORDABILITY_GOAL, REPORTABILITY_GOAL
from ...tools.tools import latest_decisions
from ...types.dossier import DossierLeg
from ..specialists import get_specialists


def _run_specialist(name: str, goal: str, state: dict) -> dict:
    """ invoke one worker sub-graph and map its result back as its leg of the dossier; its transcript stays behind """

    # the Coordinator narrows the goal when it re-dispatches
    task = state.get("tasks", {}).get(name) or goal
    try:
        result = get_specialists()[name].invoke(
            {"task": task, "incident": state["incident"], "messages": [], "rounds": 0,
             "decisions": [], "retrieved": {}, "proposal": None},
            {"recursion_limit": settings.graph_recursion_limit},
        )
    except GraphRecursionError:
        # the independent hard cap: a worker that hits it ends with no proposal, not a crash
        return {"dossier": {name: DossierLeg(task=task, proposal=None, decisions={}, cited={})}}

    proposal = result["proposal"]
    leg = DossierLeg(
        task=task,
        proposal=proposal,
        decisions=latest_decisions(result),
        cited={chunk_id: result["retrieved"][chunk_id] for chunk_id in proposal["chunk_ids"]} if proposal else {},
    )
    return {"dossier": {name: leg}}


def recordability_specialist_node(state: dict) -> dict:
    return _run_specialist("recordability", RECORDABILITY_GOAL, state)


def reportability_specialist_node(state: dict) -> dict:
    return _run_specialist("reportability", REPORTABILITY_GOAL, state)


def hazard_control_specialist_node(state: dict) -> dict:
    return _run_specialist("hazard_control", HAZARD_CONTROL_GOAL, state)
