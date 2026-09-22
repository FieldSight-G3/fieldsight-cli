from fieldsight.schemas.rule_decision import RuleDecision
from fieldsight.schemas.rule_input import R1Inputs


SOURCES = [
    "29 CFR 1904.4",
    "29 CFR 1904.5",
    "29 CFR 1904.7(b)(1)",
]

GENERAL_CRITERIA = (
    "death",
    "days_away",
    "restricted_days",
    "job_transfer",
    "medical_treatment_beyond_first_aid",
    "loss_of_consciousness",
    "significant_diagnosis",
)


def recordability(data: R1Inputs) -> RuleDecision:
    inputs = data.model_dump(mode="json")

    if data.work_related is None:
        return _insufficient(inputs, "work_related")

    if data.new_case is None:
        return _insufficient(inputs, "new_case")

    if not data.work_related or not data.new_case:
        return RuleDecision(
            rule_id="R1",
            outcome="not_recordable",
            inputs=inputs,
            sources=SOURCES,
        )

    for field_name in GENERAL_CRITERIA:
        if getattr(data, field_name) is None:
            return _insufficient(inputs, field_name)

    days_away = data.days_away
    restricted_days = data.restricted_days

    if days_away is None:
        return _insufficient(inputs, "days_away")

    if restricted_days is None:
        return _insufficient(inputs, "restricted_days")

    meets_criteria = any(
        (
            data.death,
            days_away > 0,
            restricted_days > 0,
            data.job_transfer,
            data.medical_treatment_beyond_first_aid,
            data.loss_of_consciousness,
            data.significant_diagnosis,
        )
    )

    return RuleDecision(
        rule_id="R1",
        outcome="recordable" if meets_criteria else "not_recordable",
        inputs=inputs,
        sources=SOURCES,
    )


def _insufficient(
    inputs: dict[str, object],
    field_name: str,
) -> RuleDecision:
    return RuleDecision(
        rule_id="R1",
        outcome="insufficient_data",
        inputs=inputs,
        sources=SOURCES,
        missing_field=field_name,
    )