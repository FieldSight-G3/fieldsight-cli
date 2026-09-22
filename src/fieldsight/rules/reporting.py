from datetime import timedelta

from fieldsight.schemas.rule_decision import RuleDecision
from fieldsight.schemas.rule_input import R2Inputs


SOURCES = [
    "29 CFR 1904.39(a)(1)",
    "29 CFR 1904.39(a)(2)",
    "29 CFR 1904.39(b)(6)",
    "29 CFR 1904.39(b)(7)",
    "29 CFR 1904.39(b)(10)",
    "29 CFR 1904.39(b)(11)",
]

AMPUTATION_EXCLUSIONS = {
    "avulsion",
    "enucleation",
    "degloving",
    "scalping",
    "severed_ear",
    "broken_tooth",
    "chipped_tooth",
}


def reporting_clock(data: R2Inputs) -> RuleDecision:
    inputs = data.model_dump(mode="json")

    for field_name in ("work_related", "event_type"):
        if getattr(data, field_name) is None:
            return _insufficient(inputs, field_name)

    if not data.work_related or data.event_type == "other":
        return _decision(inputs, "not_reportable")

    for field_name in ("incident_at", "event_at", "learned_at"):
        if getattr(data, field_name) is None:
            return _insufficient(inputs, field_name)

    incident_at = data.incident_at
    event_at = data.event_at
    learned_at = data.learned_at

    if incident_at is None or event_at is None or learned_at is None:
        return _insufficient(inputs, "incident_at")

    if event_at < incident_at:
        return _insufficient(inputs, "event_at")

    elapsed = event_at - incident_at

    if data.event_type == "fatality":
        # Exactly 30 days still qualifies.
        if elapsed > timedelta(days=30):
            return _decision(inputs, "not_reportable")

        return _decision(
            inputs,
            "reportable",
            deadline=learned_at + timedelta(hours=8),
        )

    # Hospitalization, amputation and eye loss must occur
    # within exactly 24 hours of the incident.
    if elapsed > timedelta(hours=24):
        return _decision(inputs, "not_reportable")

    if data.event_type == "inpatient_hospitalization":
        if data.admission_reason is None:
            return _insufficient(inputs, "admission_reason")

        if data.admission_reason in {
            "observation_only",
            "diagnostic_testing_only",
        }:
            return _decision(inputs, "not_reportable")

    if data.event_type == "amputation":
        if data.amputation_detail is None:
            return _insufficient(inputs, "amputation_detail")

        if data.amputation_detail in AMPUTATION_EXCLUSIONS:
            return _decision(inputs, "not_reportable")

    return _decision(
        inputs,
        "reportable",
        deadline=learned_at + timedelta(hours=24),
    )


def _decision(
    inputs: dict[str, object],
    outcome: str,
    *,
    deadline=None,
) -> RuleDecision:
    return RuleDecision(
        rule_id="R2",
        outcome=outcome,
        inputs=inputs,
        sources=SOURCES,
        deadline=deadline,
    )


def _insufficient(
    inputs: dict[str, object],
    field_name: str,
) -> RuleDecision:
    return RuleDecision(
        rule_id="R2",
        outcome="insufficient_data",
        inputs=inputs,
        sources=SOURCES,
        missing_field=field_name,
    )