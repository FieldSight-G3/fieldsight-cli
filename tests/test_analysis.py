from datetime import UTC, datetime
from typing import Any

from fieldsight.analysis import analyze_incident
from fieldsight.repository import (
    IncidentRepository,
    ReviewQueueRepository,
    RunRecordRepository,
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
    saved = RunRecordRepository().get(analysis.run_id)
    assert saved is not None
    assert saved.incident_id == incident_id
    assert saved.rule_invocations is not None
    assert len(saved.rule_invocations["items"]) == len(analysis.results.invocations)
    stored = incidents.get(incident_id)
    assert stored is not None
    assert stored.outcome is not None

def test_low_confidence_records_gate_and_review():
    fields = normalized_fields()
    fields["confidences"]["incident_at"] = 0.59
    incident_id = IncidentRepository().create("Substation 7", fields)
    analysis = analyze_incident(incident_id)
    saved = RunRecordRepository().get(analysis.run_id)
    assert saved is not None
    assert saved.rule_invocations is not None
    assert len(saved.rule_invocations["items"]) == 1
    assert saved.escalation_triggers is not None
    assert "confidence_gate" in saved.escalation_triggers
    pending = ReviewQueueRepository().list_pending()
    assert any(item.incident_id == incident_id for item in pending)
