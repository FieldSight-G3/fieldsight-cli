from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fieldsight.harness.run.lifecycle import run_turn
from fieldsight.repository import (
    IncidentRepository,
    ReviewQueueRepository,
    RunRecordRepository,
)
from fieldsight.schemas.run_records import ModelCall, ToolInvocation
from fieldsight.types.run import WorkflowResult


def normalized_fields() -> dict[str, Any]:
    return {
        "work_related": True,
        "new_case": True,
        "incident_at": datetime(2026, 9, 22, 8, tzinfo=UTC).isoformat(),
        "event_at": None,
        "learned_at": None,
        "event_type": "other",
        "admission_reason": None,
        "amputation_detail": None,
        "treatments": [],
        "death": False,
        "days_away": 1,
        "restricted_days": 0,
        "job_transfer": False,
        "loss_of_consciousness": False,
        "significant_diagnosis": False,
        "confidences": {"incident_at": 0.99, "days_away": 0.99}
    }


def no_answer(question: str, objections: list[str]):
    raise AssertionError("analyze never answers from retrieval")


def analyze(incident_id: object, dispatched: list[str]):
    """ analyze with the graph stubbed: it records each dispatch and returns an approved, empty dossier """

    def workflow(incident, question, correlation_id):
        dispatched.append(incident.incident_id)
        return WorkflowResult(dossier={}, workers_dispatched=["recordability"], reviewer_approved=True, reviewer_iterations=1)

    return run_turn({"command": "analyze", "incident_id": str(incident_id)}, workflow=workflow, answerer=no_answer)


def test_ready_incident_runs_the_workflow_and_records_the_run():
    incident_id = IncidentRepository().create("Substation 7", normalized_fields())
    dispatched: list[str] = []
    run = analyze(incident_id, dispatched)

    assert dispatched == [str(incident_id)]
    saved = RunRecordRepository().get(run.run_id)
    assert saved is not None and saved.command == "analyze" and saved.incident_id == incident_id
    assert saved.workers_dispatched == {"items": ["recordability"], "plans": []}
    assert saved.rule_invocations is not None
    assert {"R5", "R1"} <= {item["decision"]["rule_id"] for item in saved.rule_invocations["items"]}
    stored = IncidentRepository().get(incident_id)
    assert stored is not None and stored.outcome is not None


def test_low_confidence_routes_to_analyst_and_queues_for_review():
    fields = normalized_fields()
    fields["confidences"]["incident_at"] = 0.59
    incident_id = IncidentRepository().create("Substation 7", fields)
    dispatched: list[str] = []
    run = analyze(incident_id, dispatched)

    assert dispatched == [] and run.route == "route_to_analyst"
    saved = RunRecordRepository().get(run.run_id)
    assert saved is not None and saved.escalation_triggers is not None
    assert saved.escalation_triggers["checks"]["confidence_gate"]["fired"] is True
    assert any(item.incident_id == incident_id for item in ReviewQueueRepository().list_pending())


def test_unknown_incident_still_leaves_a_run_record():
    dispatched: list[str] = []
    run = analyze("INC-2026-0412", dispatched)

    assert dispatched == [] and run.route == "route_to_analyst" and run.escalation is None
    saved = RunRecordRepository().get(run.run_id)
    assert saved is not None and saved.incident_id is None

def test_workflow_records_land_in_the_run_record():
    incident_id = IncidentRepository().create("Substation 7", normalized_fields())
    plan = {"trigger": "initial", "dispatches": [{"worker": "recordability", "reason": "treatment beyond first aid"}],
            "energized_equipment_quote": None, "ungrounded": []}
    tool = ToolInvocation(agent="recordability", tool="evaluate_rule", args={"rule_id": "R1"}, args_hash="h", outcome="recordable")
    call = ModelCall(agent="recordability", model_id="m", input_tokens=10, output_tokens=2, latency_ms=5, cost_usd=Decimal("0.001"))

    def workflow(incident, question, correlation_id):
        return WorkflowResult(dossier={}, workers_dispatched=["recordability"], reviewer_approved=True, reviewer_iterations=1,
                              plans=[plan], tool_invocations=[tool], model_calls=[call], reviewer_verdicts=[None])

    run = run_turn({"command": "analyze", "incident_id": str(incident_id)}, workflow=workflow, answerer=no_answer)
    saved = RunRecordRepository().get(run.run_id)

    assert saved.workers_dispatched == {"items": ["recordability"], "plans": [plan]}
    assert saved.tool_invocations == {"items": [tool.model_dump(mode="json")]}
    assert saved.model_calls["items"][0]["cost_usd"] == "0.001"   # Decimal survives as exact text, not a float
    assert saved.reviewer_verdicts == {"items": [None]}           # a Reviewer with no verdict stays visible as null
