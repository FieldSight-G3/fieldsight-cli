from datetime import UTC, datetime

from langchain_core.messages import AIMessage

from fieldsight.graph.nodes.supervision import recordability_specialist_node
from fieldsight.prompts import GOALS
from fieldsight.schemas.incidents import NormalizedIncident

AT = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)

# stitches and 3 days away: recordable, column H
INCIDENT = NormalizedIncident(
    incident_id="inc-1", work_related=True, new_case=True, incident_at=AT, event_at=None, learned_at=AT,
    event_type="other", admission_reason=None, amputation_detail=None, treatments=["sutures"], death=False,
    days_away=3, restricted_days=0, job_transfer=False, loss_of_consciousness=False, significant_diagnosis=False,
    confidences={"days_away": 0.95}).model_dump(mode="json")
# the analyst whose thread the worker's tool calls are keyed to
ANALYST = "analyst-1"


def calls(*requests) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"{name}-{i}"} for i, (name, args) in enumerate(requests)])


def test_leg_carries_the_proposal_and_only_what_it_rests_on(script):
    script([
        calls(("evaluate_rule", {"rule_id": "R3"})),
        calls(("evaluate_rule", {"rule_id": "R1"})),
        calls(("evaluate_rule", {"rule_id": "R4"}), ("search_knowledge_base", {"query": "days away"})),
        calls(("propose_classification", {"proposal": {"outcome": "recordable", "log_column": "H", "day_count": 3,
                                                       "rationale": "Days away [1].", "chunk_ids": ["CFR-1904-a"]}})),
        AIMessage("Proposed."),
    ])

    leg = recordability_specialist_node({"analyst_id": ANALYST, "incident": INCIDENT})["dossier"]["recordability"]

    assert leg["task"] == GOALS["recordability"]
    assert leg["proposal"]["log_column"] == "H"
    assert set(leg["decisions"]) == {"R1", "R3", "R4"}
    assert leg["cited"]["CFR-1904-a"]["text"] == "text of 1904.39"
    # the worker's transcript never reaches the dossier
    assert set(leg) == {"task", "proposal", "decisions", "cited"}


def test_a_narrowed_task_is_recorded_and_no_proposal_cites_nothing(script):
    script([AIMessage("Nothing to propose.")])

    leg = recordability_specialist_node(
        {"analyst_id": ANALYST, "incident": INCIDENT, "tasks": {"recordability": "Check the day count against the 180-day cap."}}
    )["dossier"]["recordability"]

    # the leg records the goal and the Reviewer's narrowing; the narrowing reached the worker in its system message
    assert leg["task"].endswith("The Reviewer narrowed your goal: Check the day count against the 180-day cap.")
    assert leg["proposal"] is None
    assert leg["cited"] == {}


def test_a_re_dispatch_after_no_proposal_keeps_the_rule_decisions(script):
    script([AIMessage("Nothing to propose.")])
    r3 = {"rule_id": "R3", "outcome": "beyond_first_aid", "inputs": {"treatments": ["sutures"]},
          "sources": ["29 CFR 1904.7(b)(5)(ii)"], "missing_field": None, "deadline": None, "log_column": None,
          "day_count": None, "exclusion": None}
    failed = {"task": GOALS["recordability"], "proposal": None, "decisions": {"R3": r3}, "cited": {}}

    leg = recordability_specialist_node(
        {"analyst_id": ANALYST, "incident": INCIDENT, "review_iterations": 1, "dossier": {"recordability": failed}}
    )["dossier"]["recordability"]

    # the rules are deterministic on the same incident, so the second attempt starts from the first one's decisions
    assert leg["decisions"]["R3"]["outcome"] == "beyond_first_aid"
    assert "Your rule decisions still stand" in leg["task"]


def test_a_first_dispatch_with_the_default_goal_gets_no_reviewer_feedback(script):
    script([AIMessage("Nothing to propose.")])

    leg = recordability_specialist_node(
        {"analyst_id": ANALYST, "incident": INCIDENT, "tasks": dict(GOALS)})["dossier"]["recordability"]

    # the Coordinator puts the default goals in tasks on a new turn; that is not a narrowing
    assert leg["task"] == GOALS["recordability"]
