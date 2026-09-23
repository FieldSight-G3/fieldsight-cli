"""R1: evaluate recordability from validated incident facts."""

from fieldsight.schemas.rule_decision import RuleDecision
from fieldsight.schemas.rule_input import R1Inputs

RECORDING_REQUIREMENT = "29 CFR 1904.4(a)"
WORK_RELATEDNESS = "29 CFR 1904.5"
NEW_CASE = "29 CFR 1904.6"
GENERAL_CRITERIA = "29 CFR 1904.7(b)(1)"
DEATH = "29 CFR 1904.7(b)(2)"
DAYS_AWAY = "29 CFR 1904.7(b)(3)"
RESTRICTED_OR_TRANSFERRED = "29 CFR 1904.7(b)(4)"
MEDICAL_TREATMENT = "29 CFR 1904.7(b)(5)"
LOSS_OF_CONSCIOUSNESS = "29 CFR 1904.7(b)(6)"
SIGNIFICANT_DIAGNOSIS = "29 CFR 1904.7(b)(7)"

def recordability(data: R1Inputs) -> RuleDecision:
    inputs = data.model_dump(mode="json")

    if data.work_related is None:
        return _insufficient(inputs, "work_related", [WORK_RELATEDNESS])
    if not data.work_related:
        return _decision(inputs, "not_recordable", [RECORDING_REQUIREMENT, WORK_RELATEDNESS])

    if data.new_case is None:
        return _insufficient(inputs, "new_case", [NEW_CASE])
    if not data.new_case:
        return _decision(inputs, "not_recordable", [RECORDING_REQUIREMENT, NEW_CASE])

    matched_sources: list[str] = []
    if data.death is True:
        matched_sources.append(DEATH)
    if data.days_away is not None and data.days_away > 0:
        matched_sources.append(DAYS_AWAY)
    if (data.restricted_days is not None and data.restricted_days > 0) or data.job_transfer is True:
        matched_sources.append(RESTRICTED_OR_TRANSFERRED)
    if data.medical_treatment_beyond_first_aid is True:
        matched_sources.append(MEDICAL_TREATMENT)
    if data.loss_of_consciousness is True:
        matched_sources.append(LOSS_OF_CONSCIOUSNESS)
    if data.significant_diagnosis is True:
        matched_sources.append(SIGNIFICANT_DIAGNOSIS)

    if matched_sources:
        return _decision(
            inputs,
            "recordable",
            [RECORDING_REQUIREMENT, WORK_RELATEDNESS, NEW_CASE, *matched_sources]
        )

    required_fields = (
        ("death", DEATH),
        ("days_away", DAYS_AWAY),
        ("restricted_days", RESTRICTED_OR_TRANSFERRED),
        ("job_transfer", RESTRICTED_OR_TRANSFERRED),
        ("medical_treatment_beyond_first_aid", MEDICAL_TREATMENT),
        ("loss_of_consciousness", LOSS_OF_CONSCIOUSNESS),
        ("significant_diagnosis", SIGNIFICANT_DIAGNOSIS)
    )
    for field_name, source in required_fields:
        if getattr(data, field_name) is None:
            return _insufficient(inputs, field_name, [source])

    return _decision(inputs, "not_recordable", [RECORDING_REQUIREMENT, GENERAL_CRITERIA])

def _decision(inputs: dict[str, object], outcome: str, sources: list[str]) -> RuleDecision:
    return RuleDecision(
        rule_id="R1",
        outcome=outcome,
        inputs=inputs,
        sources=sources
    )

def _insufficient(inputs: dict[str, object], missing_field: str, sources: list[str]) -> RuleDecision:
    return RuleDecision(
        rule_id="R1",
        outcome="insufficient_data",
        inputs=inputs,
        sources=sources,
        missing_field=missing_field
    )