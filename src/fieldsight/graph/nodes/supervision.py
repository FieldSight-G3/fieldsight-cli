""" nodes for the Coordinator and the worker sub-graphs it dispatches """

from langgraph.errors import GraphRecursionError

from ...config import settings
from ...prompts import GOALS
from ...types.dossier import DossierLeg
from ..specialists import get_specialists


def _run_specialist(name: str, state: dict) -> dict:
    """ invoke one worker sub-graph and map its result back as its leg of the dossier; its transcript stays behind """

    # the Coordinator narrows the goal when it re-dispatches
    task = state.get("tasks", {}).get(name) or GOALS[name]
    try:
        result = get_specialists()[name].invoke(
            {"task": task, "incident": state["incident"], "messages": [], "rounds": 0,
             "decisions": {}, "retrieved": {}, "proposal": None},
            {"recursion_limit": settings.bounds.max_graph_recursion_depth},
        )
    except GraphRecursionError:
        # the independent hard cap: a worker that hits it ends with no proposal, not a crash
        return {"dossier": {name: DossierLeg(task=task, proposal=None, decisions={}, cited={})}}

    proposal = result["proposal"]
    leg = DossierLeg(
        task=task,
        proposal=proposal,
        decisions=result["decisions"],
        cited={chunk_id: result["retrieved"][chunk_id] for chunk_id in proposal["chunk_ids"]} if proposal else {},
    )
    return {"dossier": {name: leg}}


def recordability_specialist_node(state: dict) -> dict:
    return _run_specialist("recordability", state)


def reportability_specialist_node(state: dict) -> dict:
    return _run_specialist("reportability", state)


def hazard_control_specialist_node(state: dict) -> dict:
    return _run_specialist("hazard_control", state)
