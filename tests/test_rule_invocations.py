from datetime import UTC, datetime, timedelta

from fieldsight.rules.engine import evaluate_incident
from fieldsight.schemas.incidents import NormalizedIncident


def test_every_rule_invocation_is_recorded() -> None:
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
            "days_away": 0.93,
        }
    )
    results = evaluate_incident(incident)
    assert len(results.invocations) == 5
    assert [
        invocation.decision.rule_id
        for invocation in results.invocations
    ] == ["R5", "R3", "R1", "R2", "R4"]
    assert all(
        invocation.incident_id == "INC-001"
        for invocation in results.invocations
    )
    assert all(
        invocation.recorded_at.tzinfo is not None
        for invocation in results.invocations
    )
    assert all(
        invocation.decision.inputs
        for invocation in results.invocations
    )
    assert all(
        invocation.decision.sources
        for invocation in results.invocations
    )
    
def test_low_confidence_stops_after_r5() -> None:
    incident_at = datetime(
        2026, 9, 22, 8, 0, tzinfo=UTC
    )

    incident = NormalizedIncident(
        incident_id="INC-LOW-CONFIDENCE",
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
            "event_type": 0.59,
            "days_away": 0.95,
        },
    )

    results = evaluate_incident(incident)

    assert results.confidence.outcome == "human_determination"
    assert results.treatment is None
    assert results.recordability is None
    assert results.reporting is None
    assert results.log_classification is None

    assert len(results.invocations) == 1
    assert results.invocations[0].decision.rule_id == "R5"