"""One writer per turn: an escalated turn leaves one run record and one reviewable queue row holding its dossier."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, delete, insert, select

from fieldsight.harness.run.lifecycle import run_turn
from fieldsight.repository import (
    IncidentRepository,
    ReviewQueueRepository,
    RunRepository,
)
from fieldsight.types.run import WorkflowResult


def normalized_fields() -> dict[str, Any]:
    """ a ready incident: every required field present and confident """
    return {
        "work_related": True, "new_case": True, "incident_at": datetime(2026, 9, 22, 8, tzinfo=UTC).isoformat(),
        "event_at": None, "learned_at": None, "event_type": "other", "admission_reason": None, "amputation_detail": None,
        "treatments": [], "death": False, "days_away": 1, "restricted_days": 0, "job_transfer": False,
        "loss_of_consciousness": False, "significant_diagnosis": False,
        "confidences": {"incident_at": 0.99, "days_away": 0.99},
    }


def no_answer(question: str, objections: list[str]):
    raise AssertionError("analyze never answers from retrieval")

HIT = {"doc_id": "CFR-1904", "chunk_id": "CFR-1904-0123456789ab", "text": "1904.7(b)(3)"}
DOSSIER = {"recordability": {"task": "t", "decisions": {}, "cited": {HIT["chunk_id"]: HIT},
                             "proposal": {"outcome": "recordable", "log_column": "H", "day_count": 1, "missing_field": None,
                                          "rationale": "Days away [1].", "chunk_ids": [HIT["chunk_id"]]}}}


@pytest.fixture
def analyst():
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


def rejected_workflow(incident, question, correlation_id):
    """ the graph stubbed: the Reviewer never approved, so the reviewer trigger fires """
    return WorkflowResult(dossier=DOSSIER, workers_dispatched=["recordability"], reviewer_approved=False, reviewer_iterations=2)


def rows_for(incident_id):
    runs, queue = RunRepository(), ReviewQueueRepository()
    with runs.engine.connect() as connection:
        run_ids = connection.execute(select(runs.table.c.run_id).where(runs.table.c.incident_id == incident_id)).scalars().all()
        queue_ids = connection.execute(select(queue.table.c.queue_id).where(queue.table.c.incident_id == incident_id)).scalars().all()
    return run_ids, queue_ids


def test_an_escalated_workflow_turn_writes_once_with_its_dossier(analyst):
    incident_id = IncidentRepository().create("Substation 7", normalized_fields())

    run = run_turn({"command": "analyze", "incident_id": str(incident_id)}, workflow=rejected_workflow, answerer=no_answer,
                   analyst_id=analyst)

    assert run.escalation is not None and "reviewer" in run.escalation.fired
    run_ids, queue_ids = rows_for(incident_id)
    assert run_ids == [run.run_id] and len(queue_ids) == 1
    pending = ReviewQueueRepository().get_pending(queue_ids[0])
    assert pending is not None
    assert pending.submitting_analyst_id == analyst
    assert pending.original_payload == DOSSIER
    assert set(pending.original_citations) == {HIT["chunk_id"]}


def test_escalating_without_the_verified_analyst_writes_nothing():
    incident_id = IncidentRepository().create("Substation 7", normalized_fields())

    with pytest.raises(ValueError, match="no review snapshot"):
        run_turn({"command": "analyze", "incident_id": str(incident_id)}, workflow=rejected_workflow, answerer=no_answer)

    assert rows_for(incident_id) == ([], [])
