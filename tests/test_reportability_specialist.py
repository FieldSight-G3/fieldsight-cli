from datetime import UTC, datetime

from langchain_core.messages import AIMessage, ToolMessage

from fieldsight.graph.specialists import get_specialists
from fieldsight.schemas.incidents import NormalizedIncident

AT = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
ADMITTED = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)

# P4's shape: an overnight stay for observation only, inside the 24-hour window
INCIDENT = NormalizedIncident(
    incident_id="inc-4", work_related=True, new_case=True, incident_at=AT, event_at=ADMITTED, learned_at=ADMITTED,
    event_type="inpatient_hospitalization", admission_reason="observation_only", amputation_detail=None,
    treatments=[], death=False, days_away=0, restricted_days=0, job_transfer=False, loss_of_consciousness=False,
    significant_diagnosis=False, confidences={"event_type": 0.95}).model_dump(mode="json")


def calls(*requests) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"{name}-{i}"} for i, (name, args) in enumerate(requests)])


def test_must_find_the_exclusion_not_just_the_clock(script):
    script([
        calls(("evaluate_rule", {"rule_id": "R2"}), ("search_knowledge_base", {"query": "1904.39 hospitalization"})),
        calls(("propose_reporting_determination", {"proposal": {
            "outcome": "not_reportable", "chunk_ids": ["CFR-1904-a"], "rationale": "Hospitalized within 24 hours [1]."}})),
        calls(("propose_reporting_determination", {"proposal": {
            "outcome": "not_reportable", "exclusion": "observation_only", "chunk_ids": ["CFR-1904-a"],
            "rationale": "Observation only is not in-patient hospitalization [1]."}})),
    ])

    state = get_specialists()["reportability"].invoke(
        {"worker": "reportability", "task": "test", "incident": INCIDENT, "messages": [], "rounds": 0,
         "decisions": [], "retrieved": [], "proposal": None})

    clock_only = next(m for m in state["messages"] if isinstance(m, ToolMessage) and m.name == "propose_reporting_determination")
    assert '"rejected"' in clock_only.text
    assert state["proposal"]["exclusion"] == "observation_only"
