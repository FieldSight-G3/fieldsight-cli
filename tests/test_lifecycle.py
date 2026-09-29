from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, delete, insert

from fieldsight.harness.run.lifecycle import run_turn
from fieldsight.repository import (
    IncidentRepository,
    ReviewQueueRepository,
    RunRecordRepository,
)
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


@pytest.fixture
def analyst():
    """ the verified submitting analyst an escalated turn records on its queue row """
    queue = ReviewQueueRepository()
    analysts = Table("analysts", MetaData(), autoload_with=queue.engine)
    with queue.engine.begin() as connection:
        analyst_id = connection.execute(
            insert(analysts).values(email=f"analyst-{uuid4()}@example.invalid", name="analyst").returning(analysts.c.analyst_id)
        ).scalar_one()
    yield analyst_id
    with queue.engine.begin() as connection:
        connection.execute(delete(queue.table).where(queue.table.c.submitting_analyst_id == analyst_id))
        connection.execute(delete(analysts).where(analysts.c.analyst_id == analyst_id))


def analyze(incident_id: object, dispatched: list[str], analyst_id: object = None):
    """ analyze with the graph stubbed: it records each dispatch and returns an approved, empty dossier """

    def workflow(incident, question, correlation_id):
        dispatched.append(incident.incident_id)
        return WorkflowResult(dossier={}, workers_dispatched=["recordability"], reviewer_approved=True, reviewer_iterations=1)

    return run_turn({"command": "analyze", "incident_id": str(incident_id)}, workflow=workflow, answerer=no_answer,
                    analyst_id=analyst_id)


def test_ready_incident_runs_the_workflow_and_records_the_run():
    incident_id = IncidentRepository().create("Substation 7", normalized_fields())
    dispatched: list[str] = []
    run = analyze(incident_id, dispatched)

    assert dispatched == [str(incident_id)]
    saved = RunRecordRepository().get(run.run_id)
    assert saved is not None and saved.command == "analyze" and saved.incident_id == incident_id
    assert saved.workers_dispatched == {"items": ["recordability"]}
    assert saved.rule_invocations is not None
    assert {"R5", "R1"} <= {item["decision"]["rule_id"] for item in saved.rule_invocations["items"]}
    stored = IncidentRepository().get(incident_id)
    assert stored is not None and stored.outcome is not None


def test_low_confidence_routes_to_analyst_and_queues_for_review(analyst):
    fields = normalized_fields()
    fields["confidences"]["incident_at"] = 0.59
    incident_id = IncidentRepository().create("Substation 7", fields)
    dispatched: list[str] = []
    run = analyze(incident_id, dispatched, analyst)

    assert dispatched == [] and run.route == "route_to_analyst"
    saved = RunRecordRepository().get(run.run_id)
    assert saved is not None and saved.escalation_triggers is not None
    assert saved.escalation_triggers["checks"]["confidence_gate"]["fired"] is True
    queue = ReviewQueueRepository()
    [item] = [item for item in queue.list_pending() if item.incident_id == incident_id]
    # the queued case can be reviewed: it records who submitted it
    pending = queue.get_pending(item.queue_id)
    assert pending is not None and pending.submitting_analyst_id == analyst


def test_unknown_incident_still_leaves_a_run_record():
    dispatched: list[str] = []
    run = analyze("INC-2026-0412", dispatched)

    assert dispatched == [] and run.route == "route_to_analyst" and run.escalation is None
    saved = RunRecordRepository().get(run.run_id)
    assert saved is not None and saved.incident_id is None
