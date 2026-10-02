from fieldsight.schemas.rule_decision import RuleDecision
from fieldsight.schemas.rule_input import R4Inputs

# the regulation paragraphs only: the corpus has no Form 300 column definitions, and listing them sent workers and the
# Reviewer searching for a document that isn't there, which made every column J case slow and often rejected
SOURCES = [
    "29 CFR 1904.7(b)(3)",
    "29 CFR 1904.29(b)(3)",
]

# the 1904.7(b) paragraph that says how each column's kind of case is entered on the log
COLUMN_PROVISIONS = {
    "G": "29 CFR 1904.7(b)(2)",
    "H": "29 CFR 1904.7(b)(3)",
    "I": "29 CFR 1904.7(b)(4)",
    "J": "29 CFR 1904.7(b)(5)",
}


def column_sources(column: str) -> list[str]:
    """ the provisions a column decision applied: the paragraph for that kind of case, then the log's column rules """

    return [COLUMN_PROVISIONS[column], "29 CFR 1904.29(b)(3)"]


def log_classification(data: R4Inputs) -> RuleDecision:
    inputs = data.model_dump(mode="json")

    required_fields = (
        "recordable",
        "death",
        "days_away",
        "restricted_days",
        "job_transfer",
    )

    for field_name in required_fields:
        if getattr(data, field_name) is None:
            return RuleDecision(
                rule_id="R4",
                outcome="insufficient_data",
                inputs=inputs,
                sources=SOURCES,
                missing_field=field_name,
            )

    recordable = data.recordable
    death = data.death
    days_away = data.days_away
    restricted_days = data.restricted_days
    job_transfer = data.job_transfer
    assert (
        recordable is not None
        and death is not None
        and days_away is not None
        and restricted_days is not None
        and job_transfer is not None
    )

    if not recordable:
        return RuleDecision(
            rule_id="R4",
            outcome="not_recordable",
            inputs=inputs,
            sources=SOURCES,
        )

    # Combined count cannot exceed 180.
    day_count = min(days_away + restricted_days, 180)

    if death:
        column = "G"
    elif days_away > 0:
        column = "H"
    elif restricted_days > 0 or job_transfer:
        column = "I"
    else:
        column = "J"

    return RuleDecision(
        rule_id="R4",
        outcome=column,
        inputs=inputs,
        sources=column_sources(column),
        log_column=column,
        day_count=day_count,
    )