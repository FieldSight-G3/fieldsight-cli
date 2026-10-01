""" the Dossier Reviewer: a harness stage that judges the dossier on its own checkpointer thread, then routes the cycle """

import json
import threading

from langgraph.errors import GraphRecursionError

from ...checkpoint import postgres_checkpointer, thread_id
from ...config import settings
from ...prompts import PROMPTS
from ...schemas.review import ReviewVerdict
from ...tools.tools import TOOLSETS
from ..specialists import build_specialist
from ..trace import record

_REVIEWER = None
_REVIEWER_LOCK = threading.Lock()


def get_reviewer():
    """ the compiled Reviewer, built once: the specialist factory with its brief, its tools and a checkpointer """

    global _REVIEWER
    # the Reviewer can be reached from concurrent legs; only one of them may build it
    with _REVIEWER_LOCK:
        if _REVIEWER is None:
            _REVIEWER = build_specialist("reviewer", PROMPTS["reviewer"], TOOLSETS["reviewer"], postgres_checkpointer())
    return _REVIEWER


def reviewer_node(state: dict) -> dict:
    """ judge the dossier only, never a worker's transcript, on the Reviewer's own thread """

    config = {
        # one thread per (analyst, incident, participant), so the Reviewer's state never merges with a worker's
        "configurable": {"thread_id": thread_id(state["analyst_id"], state["incident"]["incident_id"], "reviewer")},
        "recursion_limit": settings.bounds.max_graph_recursion_depth,
    }

    reviewer = get_reviewer()
    seen = len(reviewer.get_state(config).values.get("messages", []))
    try:
        result = reviewer.invoke(
            {"task": json.dumps(state["dossier"]), "rounds": 0, "proposal": None}, config)
        verdict = ReviewVerdict.model_validate(result["proposal"]) if result["proposal"] else None
        tools, calls = record("reviewer", result["messages"][seen:], config["configurable"]["thread_id"])
    except GraphRecursionError:
        # the independent hard cap: no verdict, which the route treats as not approved
        verdict, tools, calls = None, [], []

    # the Coordinator re-dispatches each rejected worker with its narrowed goals
    tasks: dict[str, str] = {}
    for rejection in verdict.rejections if verdict else []:
        tasks[rejection.worker] = f"{tasks.get(rejection.worker, '')} {rejection.narrowed_goal}".strip()

    return {
        # the verdict per iteration, for the run record; None when the Reviewer submitted none
        "reviews": [verdict],
        "review_iterations": state.get("review_iterations", 0) + 1,
        "tasks": tasks,
        "tool_invocations": tools,
        "model_calls": calls,
    }


def route_after_review(state: dict) -> str:
    """ approved, no verdict, or out of iterations: on to the eligibility check; rejected: back to the Coordinator """

    verdict = state["reviews"][-1]
    if verdict is None or verdict.approved:
        return "eligibility_check"
    if state["review_iterations"] >= settings.bounds.max_reviewer_iterations:
        return "eligibility_check"
    return "coordinator"
