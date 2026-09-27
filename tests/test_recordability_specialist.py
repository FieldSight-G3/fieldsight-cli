from datetime import UTC, datetime

from langchain_core.messages import AIMessage

from fieldsight.graph.nodes.recordability import recordability_node
from fieldsight.graph.specialists import MAX_SPECIALIST_TOOL_ROUNDS, get_specialists
from fieldsight.schemas.incidents import NormalizedIncident
from fieldsight.schemas.rule_proposal import ClassificationProposal

AT = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)

# stitches and 3 days away: recordable, column H
INCIDENT = NormalizedIncident(
    incident_id="inc-1", work_related=True, new_case=True, incident_at=AT, event_at=None, learned_at=AT,
    event_type="other", admission_reason=None, amputation_detail=None, treatments=["sutures"], death=False,
    days_away=3, restricted_days=0, job_transfer=False, loss_of_consciousness=False, significant_diagnosis=False,
    confidences={"days_away": 0.95}).model_dump(mode="json")


def calls(*requests) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"{name}-{i}"} for i, (name, args) in enumerate(requests)])


def test_loops_on_its_tools_until_a_proposal_is_accepted_and_applies_r3_r1_r4(script):
    script([
        calls(("get_incident_extraction", {}), ("evaluate_rule", {"rule_id": "R3"})),
        calls(("evaluate_rule", {"rule_id": "R1"})),
        calls(("evaluate_rule", {"rule_id": "R4"}), ("search_knowledge_base", {"query": "days away"})),
        calls(("propose_classification", {"proposal": {"outcome": "recordable", "log_column": "H", "day_count": 3,
                                                       "rationale": "Days away [1].", "chunk_ids": ["CFR-1904-a"]}})),
    ])

    update = recordability_node({"incident": INCIDENT})

    assert isinstance(update["recordability"], ClassificationProposal)
    assert update["recordability"].log_column == "H"
    assert [invocation.decision.rule_id for invocation in update["rule_invocations"]] == ["R3", "R1", "R4"]


def test_stops_at_the_round_budget(script):
    script([calls(("get_incident_extraction", {})) for _ in range(MAX_SPECIALIST_TOOL_ROUNDS)])

    state = get_specialists()["recordability"].invoke(
        {"worker": "recordability", "task": "test", "incident": INCIDENT, "messages": [], "rounds": 0,
         "decisions": [], "retrieved": [], "proposal": None})

    assert state["rounds"] == MAX_SPECIALIST_TOOL_ROUNDS
    assert state["messages"][-1].tool_calls
    assert state["proposal"] is None
