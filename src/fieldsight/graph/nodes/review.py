""" the Dossier Reviewer: a harness stage that judges the dossier on its own checkpointer thread, then routes the cycle """

import json
import threading

from langgraph.errors import GraphRecursionError

from ...checkpoint import postgres_checkpointer, thread_id
from ...config import settings
from ...prompts import GOALS, PROMPTS
from ...rules.proposal_review import rule_sentences
from ...schemas.review import Rejection, ReviewVerdict
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


def no_proposals(state: dict) -> ReviewVerdict | None:
    """ a rejection of every dispatched leg when none of them has a proposal; None when there's something to review """

    legs = state.get("dossier") or {}
    if not legs or any(leg.get("proposal") for leg in legs.values()):
        return None
    return ReviewVerdict(approved=False, rejections=[
        Rejection(worker=worker, claim="No proposal", problem="The worker ended without an accepted proposal.",
                  narrowed_goal=GOALS[worker]) for worker in legs])


def verified(dossier: dict) -> dict[str, list[dict]]:
    """ per leg, the sentences restating a rule decision whose citation the propose tool already checked: the cited
        chunk states a provision that rule applied

        The Reviewer kept rejecting these (column J "not in the chunk") although the check had confirmed them; it
        gets the check's evidence, sentence by sentence, instead of only an instruction not to
    """

    found = {}
    for worker, leg in dossier.items():
        proposal = leg.get("proposal") or {}
        if proposal.get("rationale"):
            found[worker] = [{"sentence": check["sentence"], "rules": check["rules"], "grounded_by": check["provision"]}
                             for check in rule_sentences(proposal["rationale"], proposal.get("chunk_ids") or [],
                                                         leg.get("decisions") or {}, leg.get("cited") or {})
                             if check["provision"]]
    return found


def reviewer_node(state: dict) -> dict:
    """ judge the dossier only, never a worker's transcript, on the Reviewer's own thread """

    config = {
        # one thread per (analyst, incident, participant), so the Reviewer's state never merges with a worker's
        "configurable": {"thread_id": thread_id(state["analyst_id"], state["incident"]["incident_id"], "reviewer")},
        "recursion_limit": settings.bounds.max_graph_recursion_depth,
    }

    # nothing to judge: no dispatched leg has a proposal, so the verdict is a rejection without a model call. The
    # Reviewer used to spend 25-40 s saying so. With one leg finished and another not, it still runs, so a finished
    # leg is never released unreviewed
    if (empty := no_proposals(state)) is not None:
        return {"reviews": [empty], "review_iterations": state.get("review_iterations", 0) + 1,
                "tasks": {r.worker: r.narrowed_goal for r in empty.rejections}, "tool_invocations": [], "model_calls": []}

    reviewer = get_reviewer()
    seen = len(reviewer.get_state(config).values.get("messages", []))
    try:
        # the Coordinator's plan goes with the dossier: without it, a leg the plan skipped (reportability on a case
        # with no 1904.39 event) read as missing, and the Reviewer rejected a complete dossier
        plan = (state.get("plans") or [{}])[-1]
        task = {"dispatched": plan.get("dispatches") or [], "dossier": state["dossier"],
                "verified_rule_citations": verified(state["dossier"])}
        result = reviewer.invoke({"task": json.dumps(task), "rounds": 0, "proposal": None}, config)
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
