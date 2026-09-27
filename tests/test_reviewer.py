import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from fieldsight.config import settings
from fieldsight.graph.nodes import review
from fieldsight.graph.nodes.review import reviewer_node, route_after_review
from fieldsight.schemas.review import Rejection, ReviewVerdict

NARROWED = "Find the 1904.39(b)(10) text on admission for observation only and cite it for the exclusion."

# P4's reportability leg: the exclusion is right, but the cited chunk is the clock, not (b)(10)
DOSSIER = {"reportability": {
    "task": "Is this incident reportable to OSHA, on what clock, and does an exclusion apply?",
    "proposal": {"outcome": "not_reportable", "exclusion": "observation_only", "chunk_ids": ["CFR-1904-a"],
                 "rationale": "Admission for observation only is not in-patient hospitalization [1]."},
    "decisions": {"R2": {"rule_id": "R2", "outcome": "not_reportable", "exclusion": "observation_only"}},
    "cited": {"CFR-1904-a": {"chunk_id": "CFR-1904-a", "section_path": "1904.39", "text": "within 24 hours"}},
}}
STATE = {"analyst_id": "analyst-1", "incident": {"incident_id": "inc-4"}, "dossier": DOSSIER}
THREAD = {"configurable": {"thread_id": "analyst-1:inc-4:reviewer"}}


def submit(verdict: dict) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": "submit_review", "args": {"verdict": verdict}, "id": "submit"}])


@pytest.fixture
def reviewer(script, monkeypatch):
    """ the Reviewer on an in-memory checkpointer, rebuilt on the scripted model """

    monkeypatch.setattr(review, "postgres_checkpointer", InMemorySaver)
    monkeypatch.setattr(review, "_REVIEWER", None)
    return script


def test_rejects_then_approves_on_its_own_thread(reviewer):
    reviewer([
        submit({"approved": False, "rejections": [{
            "worker": "reportability", "claim": "Admission for observation only is not in-patient hospitalization [1].",
            "problem": "the cited chunk states the 24-hour clock, not the exclusion", "narrowed_goal": NARROWED}]}),
        AIMessage("Rejected."),
        submit({"approved": True}),
        AIMessage("Approved."),
    ])

    first = reviewer_node(STATE)
    assert first["reviews"][0].approved is False
    assert first["tasks"] == {"reportability": NARROWED}
    assert first["review_iterations"] == 1

    second = reviewer_node({**STATE, "review_iterations": 1})
    assert second["reviews"][0].approved is True
    assert second["tasks"] == {}
    assert second["review_iterations"] == 2

    # one thread across both iterations, and only the dossier ever reached it
    messages = review.get_reviewer().get_state(THREAD).values["messages"]
    assert [m.content for m in messages if isinstance(m, HumanMessage)] == [json.dumps(DOSSIER)] * 2


APPROVED = ReviewVerdict(approved=True)
REJECTED = ReviewVerdict(approved=False, rejections=[
    Rejection(worker="reportability", claim="claim", problem="problem", narrowed_goal=NARROWED)])


@pytest.mark.parametrize(("verdict", "iterations", "route"), [
    (APPROVED, 1, "eligibility_check"),
    (REJECTED, 1, "coordinator"),
    (REJECTED, settings.max_review_iterations, "eligibility_check"),
    (None, 1, "eligibility_check"),
])
def test_route_after_review(verdict, iterations, route):
    assert route_after_review({"reviews": [verdict], "review_iterations": iterations}) == route
