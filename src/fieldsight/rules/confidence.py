from fieldsight.schemas.rule_decision import RuleDecision
from fieldsight.schemas.rule_input import R5Inputs


def confidence_floor(data: R5Inputs) -> RuleDecision:
    inputs = data.model_dump(mode="json")
    sources = ["FieldSight extraction-confidence policy"]

    if not data.confidences:
        return RuleDecision(
            rule_id="R5",
            outcome="insufficient_data",
            missing_field="confidences",
            inputs=inputs,
            sources=sources,
        )

    fields_below_floor = sorted(
        field
        for field, score in data.confidences.items()
        if score < data.floor
    )
    return RuleDecision(
        rule_id="R5",
        outcome=(
            "human_determination"
            if fields_below_floor
            else "ready"
        ),
        missing_field=(
            fields_below_floor[0]
            if fields_below_floor
            else None
        ),
        inputs=inputs,
        sources=sources
    )