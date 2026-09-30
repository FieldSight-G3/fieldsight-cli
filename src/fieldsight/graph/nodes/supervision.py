""" nodes for the Coordinator and the worker sub-graphs it dispatches """
import json

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError

from ...aws import clients
from ...config import settings
from ...errors import PlanError
from ...prompts import GOALS, PROMPTS
from ...schemas.plan import DispatchPlan
from ...schemas.run_records import ModelCall
from ...types.dossier import DossierLeg
from ..specialists import get_specialists
from ..trace import model_call, record


def _plan(state: dict) -> tuple[DispatchPlan, list[ModelCall]]:
    """ the fast model's plan; one retry with a schema reminder, then a typed failure (section 13); every attempt is recorded """

    model = clients.chat_model(fast=True).with_structured_output(DispatchPlan, include_raw=True)
    messages = [SystemMessage(PROMPTS["coordinator"]),
                HumanMessage(json.dumps({"fields": state["incident"], "narrative": state.get("narrative")}))]
    calls = []
    for _ in range(2):
        out = model.invoke(messages)
        calls.append(model_call("coordinator", out["raw"]))
        if out["parsed"]:
            return out["parsed"], calls
        problem = str(out["parsing_error"] or "no plan was returned")
        messages.append(HumanMessage(f"That plan was invalid: {problem}. Return one that matches the DispatchPlan schema."))
    raise PlanError("the Coordinator returned no valid plan after one retry")


def coordinator_node(state: dict) -> dict:
    """ first pass: the model plans. After a Reviewer rejection: re-dispatch only the rejected workers, no model call """
    call = []
    if state.get("review_iterations"):
        # route_after_review only comes back here on a rejection; one dispatch per rejected worker
        problems = {r.worker: r.problem for r in state["reviews"][-1].rejections}
        dispatches = [{"worker": worker, "reason": problem} for worker, problem in problems.items()]
        quote, trigger = state["plans"][-1]["energized_equipment_quote"], "reviewer_rejected"
    else:
        plan, call = _plan(state) 
        dispatches = [d.model_dump() for d in plan.dispatches]
        quote, trigger = plan.energized_equipment_quote, "initial"

    # the model chooses hazard_control; this checks its grounds are really in the narrative
    grounded = bool(quote) and quote in (state.get("narrative") or "")
    kept = [d for d in dispatches if grounded or d["worker"] != "hazard_control"]
    update = {"plans": [{"trigger": trigger, "dispatches": kept, "energized_equipment_quote": quote, 
                         "ungrounded": [d for d in dispatches if d not in kept]}],"model_calls": call}
    if trigger == "initial":
        # a new turn starts from the default goals, not last turn's narrowed ones
        update["tasks"] = dict(GOALS)
    return update


def route_after_coordinator(state: dict) -> list[str] | str:
    """ fan out to every dispatched worker at once; with none, straight to the eligibility check """

    workers = [d["worker"] for d in state["plans"][-1]["dispatches"]]
    return workers or "eligibility_check"
    
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

    tools, calls = record(name, result["messages"])
    return {"dossier": {name: leg}, "tool_invocations": tools, "model_calls": calls}


def recordability_specialist_node(state: dict) -> dict:
    return _run_specialist("recordability", state)


def reportability_specialist_node(state: dict) -> dict:
    return _run_specialist("reportability", state)


def hazard_control_specialist_node(state: dict) -> dict:
    return _run_specialist("hazard_control", state)
