"""Normalize's provenance step: the code, not the model, decides which event details a record can carry."""

from fieldsight.ingest.normalize import attach_provenance
from fieldsight.schemas.incidents import NormalizedIncident

NARRATIVE = "Employee's forearm struck a sharp clamp edge; the clinic closed the cut with sutures."


def draft(**fields) -> NormalizedIncident:
    base = {"incident_id": "", "work_related": True, "new_case": True, "incident_at": None, "event_at": None,
            "learned_at": None, "event_type": "other", "admission_reason": None, "amputation_detail": None,
            "treatments": ["sutures"], "death": False, "days_away": 0, "restricted_days": 0, "job_transfer": False,
            "loss_of_consciousness": False, "significant_diagnosis": False, "confidences": {}, "sources": {}}
    return NormalizedIncident.model_validate(base | fields)


def normalized(record: NormalizedIncident) -> NormalizedIncident:
    return attach_provenance({"draft": record, "fields": [], "narrative": NARRATIVE})


def test_a_laceration_never_carries_an_admission_reason_or_amputation_detail():
    record = normalized(draft(admission_reason="care_or_treatment", amputation_detail="broken_tooth"))
    assert record.admission_reason is None and record.amputation_detail is None
    assert record.treatments == ["sutures"]


def test_each_event_keeps_its_own_detail():
    hospitalized = normalized(draft(event_type="inpatient_hospitalization", admission_reason="observation_only",
                                    amputation_detail="fingertip"))
    assert hospitalized.admission_reason == "observation_only" and hospitalized.amputation_detail is None

    amputated = normalized(draft(event_type="amputation", amputation_detail="fingertip", admission_reason="care_or_treatment"))
    assert amputated.amputation_detail == "fingertip" and amputated.admission_reason is None
