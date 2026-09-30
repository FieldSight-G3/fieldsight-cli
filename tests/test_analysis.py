from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, delete, insert

from fieldsight.harness.analysis import ReviewSnapshot, analyze_incident
from fieldsight.harness.escalation.review import CitationReference
from fieldsight.repository import (
    IncidentRepository,
    ReviewQueueRepository,
    RunRepository,
)


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

def test_analyze_incident_records_rule_invocations():
    incidents = IncidentRepository()
    incident_id = incidents.create("Substation 7", normalized_fields())
    analysis = analyze_incident(incident_id)
    saved = RunRepository().get(analysis.run_id)
    assert saved is not None
    assert saved.incident_id == incident_id
    assert saved.rule_invocations is not None
    assert len(saved.rule_invocations["items"]) == len(analysis.results.invocations)
    stored = incidents.get(incident_id)
    assert stored is not None
    assert stored.outcome is not None

def test_low_confidence_records_gate_and_review(snapshot):
    fields = normalized_fields()
    fields["confidences"]["incident_at"] = 0.59
    incident_id = IncidentRepository().create("Substation 7", fields)
    analysis = analyze_incident(incident_id, review_snapshot=snapshot)
    saved = RunRepository().get(analysis.run_id)
    assert saved is not None
    assert saved.rule_invocations is not None
    assert len(saved.rule_invocations["items"]) == 1
    assert saved.escalation_triggers is not None
    assert saved.escalation_triggers["checks"]["confidence_gate"]["fired"] is True
    pending = ReviewQueueRepository().list_pending()
    assert any(item.incident_id == incident_id for item in pending)


@pytest.fixture
def snapshot():
    """A review snapshot from a seeded analyst; conftest does not truncate analysts."""
    queue = ReviewQueueRepository()
    analysts = Table("analysts", MetaData(), autoload_with=queue.engine)
    with queue.engine.begin() as connection:
        analyst_id = connection.execute(
            insert(analysts)
            .values(email=f"submitter-{uuid4()}@example.invalid", name="submitter")
            .returning(analysts.c.analyst_id)
        ).scalar_one()
    yield ReviewSnapshot(
        submitting_analyst_id=analyst_id,
        dossier={"narrative": "Worker slipped on wet stairs."},
        citations={"c1": CitationReference(document_id="osha-1904-7", chunk_id="osha-1904-7#3")},
    )
    with queue.engine.begin() as connection:
        connection.execute(delete(queue.table).where(queue.table.c.submitting_analyst_id == analyst_id))
        connection.execute(delete(analysts).where(analysts.c.analyst_id == analyst_id))

def test_escalated_analysis_queues_review_snapshot(snapshot):
    fields = normalized_fields()
    fields["confidences"]["incident_at"] = 0.59
    incident_id = IncidentRepository().create("Substation 7", fields)
    analysis = analyze_incident(incident_id, review_snapshot=snapshot)
    assert analysis.escalation_decision.requires_review is True
    queue = ReviewQueueRepository()
    [item] = [item for item in queue.list_pending() if item.incident_id == incident_id]
    pending = queue.get_pending(item.queue_id)
    assert pending is not None
    assert pending.submitting_analyst_id == snapshot.submitting_analyst_id
    assert pending.original_payload == snapshot.dossier
    assert pending.original_citations == snapshot.citations

def test_snapshot_is_not_queued_without_escalation(snapshot):
    incident_id = IncidentRepository().create("Substation 7", normalized_fields())
    analysis = analyze_incident(incident_id, review_snapshot=snapshot)
    assert analysis.escalation_decision.requires_review is False
    assert not any(item.incident_id == incident_id for item in ReviewQueueRepository().list_pending())

def test_escalation_without_a_snapshot_writes_nothing():
    fields = normalized_fields()
    fields["confidences"]["incident_at"] = 0.59
    incidents = IncidentRepository()
    incident_id = incidents.create("Substation 7", fields)
    with pytest.raises(ValueError, match="no review snapshot"):
        analyze_incident(incident_id)
    stored = incidents.get(incident_id)
    assert stored is not None and stored.outcome is None
    assert not any(item.incident_id == incident_id for item in ReviewQueueRepository().list_pending())
