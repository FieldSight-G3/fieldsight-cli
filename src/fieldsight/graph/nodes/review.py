""" the Dossier Reviewer: a harness stage that judges the dossier on its own checkpointer thread, then routes the cycle """

import json

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.errors import GraphRecursionError
from psycopg import Connection
from psycopg.rows import dict_row

from ...config import bounds, settings
from ...prompts import PROMPTS
from ...schemas.review import ReviewVerdict
from ...tools.tools import TOOLSETS
from ..specialists import build_specialist


def postgres_checkpointer() -> PostgresSaver:
    """ setup() only creates the checkpoint tables that are missing """

    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    saver = PostgresSaver(Connection.connect(url, autocommit=True, prepare_threshold=0, row_factory=dict_row))
    saver.setup()
    return saver


_REVIEWER = None

def get_reviewer():
    """ the compiled Reviewer, built once: the specialist factory with its brief, its tools and a checkpointer """

    global _REVIEWER
    if _REVIEWER is None:
        _REVIEWER = build_specialist("reviewer", PROMPTS["reviewer"], TOOLSETS["reviewer"], postgres_checkpointer())
    return _REVIEWER


def reviewer_node(state: dict) -> dict:
    """ judge the dossier only, never a worker's transcript, on the Reviewer's own thread """

    config = {
        # one thread per (analyst, incident, participant), so the Reviewer's state never merges with a worker's
        "configurable": {"thread_id": f"{state['analyst_id']}:{state['incident']['incident_id']}:reviewer"},
        "recursion_limit": bounds.max_graph_recursion_depth,
    }
    try:
        result = get_reviewer().invoke(
            {"task": json.dumps(state["dossier"]), "rounds": 0, "proposal": None}, config)
        verdict = ReviewVerdict.model_validate(result["proposal"]) if result["proposal"] else None
    except GraphRecursionError:
        # the independent hard cap: no verdict, which the route treats as not approved
        verdict = None

    # the Coordinator re-dispatches each rejected worker with its narrowed goals
    tasks: dict[str, str] = {}
    for rejection in verdict.rejections if verdict else []:
        tasks[rejection.worker] = f"{tasks.get(rejection.worker, '')} {rejection.narrowed_goal}".strip()

    return {
        # the verdict per iteration, for the run record; None when the Reviewer submitted none
        "reviews": [verdict],
        "review_iterations": state.get("review_iterations", 0) + 1,
        "tasks": tasks,
    }


def route_after_review(state: dict) -> str:
    """ approved, no verdict, or out of iterations: on to the eligibility check; rejected: back to the Coordinator """

    verdict = state["reviews"][-1]
    if verdict is None or verdict.approved:
        return "eligibility_check"
    if state["review_iterations"] >= bounds.max_reviewer_iterations:
        return "eligibility_check"
    return "coordinator"
