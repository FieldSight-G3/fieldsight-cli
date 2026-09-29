import pytest

from fieldsight.errors import PlanError
from fieldsight.graph.nodes import supervision
from fieldsight.graph.nodes.supervision import coordinator_node, route_after_coordinator
from fieldsight.prompts import GOALS
from fieldsight.schemas.review import Rejection, ReviewVerdict

NARRATIVE = "Lineman was repairing an energized 13.2 kV conductor when his glove contacted the phase."
STATE = {"incident": {"incident_id": "inc-1"}, "narrative": NARRATIVE, "review_iterations": 0}


class Planner:
    """ stands in for the fast model: each invoke validates the next scripted reply against the schema """

    def __init__(self, replies):
        self.replies = list(replies)

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, messages):
        return self.schema.model_validate(self.replies.pop(0))


@pytest.fixture
def plan(monkeypatch):
    """ script the Coordinator's replies; with none, any model call fails the test """

    def use(*replies):
        monkeypatch.setattr(supervision.clients, "chat_model", lambda **kwargs: Planner(replies))
    return use

def invoke(self, messages):
    reply = self.replies.pop(0)
    return None if reply is None else self.schema.model_validate(reply)

def dispatch(*workers):
    return [{"worker": worker, "reason": f"{worker} applies"} for worker in workers]


def test_plan_runs_its_workers_in_parallel(plan):
    # P4: recordability and reportability, no hazard control
    plan({"dispatches": dispatch("recordability", "reportability")})
    update = coordinator_node(STATE)
    assert route_after_coordinator(update) == ["recordability", "reportability"]
    assert update["plans"][0]["trigger"] == "initial"
    assert update["tasks"] == GOALS


@pytest.mark.parametrize(("quote", "routed"), [
    ("repairing an energized 13.2 kV conductor", ["recordability", "hazard_control"]),
    ("working on a live 69 kV bus", ["recordability"]),
])
def test_hazard_control_needs_its_quote_in_the_narrative(plan, quote, routed):
    plan({"dispatches": dispatch("recordability", "hazard_control"), "energized_equipment_quote": quote})
    update = coordinator_node(STATE)
    assert route_after_coordinator(update) == routed
    assert update["plans"][0]["ungrounded"] == ([] if "hazard_control" in routed else dispatch("hazard_control"))


def test_rejection_redispatches_only_the_rejected_worker(plan):
    plan()  # no replies: re-dispatch must not call the model
    rejected = ReviewVerdict(approved=False, rejections=[Rejection(
        worker="reportability", claim="reportable within 24 hours [1]",
        problem="the cited chunk states the clock, not the (b)(10) exclusion", narrowed_goal="find 1904.39(b)(10)")])
    state = {**STATE, "review_iterations": 1, "reviews": [rejected], "plans": [{"energized_equipment_quote": None}]}

    update = coordinator_node(state)
    assert route_after_coordinator(update) == ["reportability"]
    assert update["plans"][0]["trigger"] == "reviewer_rejected"
    assert "tasks" not in update  # the Reviewer's narrowed goal survives


def test_one_retry_then_plan_error(plan):
    invalid = {"dispatches": dispatch("hazard_control")}  # no quote, so valid_plan rejects it
    plan(invalid, {"dispatches": []})
    assert route_after_coordinator(coordinator_node(STATE)) == "eligibility_check"

    plan(None, invalid)
    with pytest.raises(PlanError):
        coordinator_node(STATE)