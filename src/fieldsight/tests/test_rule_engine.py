from datetime import UTC, datetime, timedelta

from fieldsight.rules.engine import evaluate_incident
from fieldsight.schemas.incidents import NormalizedIncident


def test_complete_incident_through_rules_engine() -> None:
    incident_at = datetime(
        2026, 9, 22, 8, 0, tzinfo=UTC
    )

    incident = NormalizedIncident(
        incident_id="INC-001",
        work_related=True,
        new_case=True,
        incident_at=incident_at,
        event_at=incident_at + timedelta(hours=10),
        learned_at=incident_at + timedelta(hours=11),
        event_type="inpatient_hospitalization",
        admission_reason="care_or_treatment",
        amputation_detail=None,
        treatments=["prescription_medication"],
        death=False,
        days_away=30,
        restricted_days=0,
        job_transfer=False,
        loss_of_consciousness=False,
        significant_diagnosis=False,
        confidences={
            "work_related": 0.98,
            "new_case": 0.95,
            "event_type": 0.97,
            "event_at": 0.94,
            "treatments": 0.91,
            "days_away": 0.93
        }
    )

    results = evaluate_incident(incident)

    assert results.confidence.outcome == "ready"
    assert results.treatment is not None
    assert results.treatment.outcome == "beyond_first_aid"

    assert results.recordability is not None
    assert results.recordability.outcome == "recordable"

    assert results.reporting is not None
    reporting = results.reporting
    assert reporting.outcome == "reportable"
    assert incident.learned_at is not None
    assert reporting.deadline == (incident.learned_at + timedelta(hours=24))

    assert results.log_classification is not None
    assert results.log_classification.log_column == "H"
    assert results.log_classification.day_count == 30