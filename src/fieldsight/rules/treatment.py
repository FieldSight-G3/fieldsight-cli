from fieldsight.schemas.rule_decision import RuleDecision
from fieldsight.schemas.rule_input import R3Inputs

FIRST_AID = {
    "nonprescription_medication_nonprescription_strength",
    "tetanus_immunization",
    "cleaning_flushing_soaking_surface_wound",
    "wound_covering",
    "hot_or_cold_therapy",
    "non_rigid_support",
    "temporary_immobilization_transport",
    "drilling_fingernail_or_toenail",
    "eye_patch",
    "foreign_body_eye_irrigation_or_swab",
    "foreign_body_non_eye_simple_means",
    "finger_guard",
    "massage",
    "fluids_for_heat_stress",
}


def medical_treatment(data: R3Inputs) -> RuleDecision:
    inputs = data.model_dump(mode="json")
    sources = ["29 CFR 1904.7(b)(5)(ii)"]

    if data.treatments is None:
        return RuleDecision(
            rule_id="R3",
            outcome="insufficient_data",
            missing_field="treatments",
            inputs=inputs,
            sources=sources,
        )

    beyond_first_aid = any(
        treatment not in FIRST_AID
        for treatment in data.treatments
    )

    return RuleDecision(
        rule_id="R3",
        outcome=(
            "beyond_first_aid"
            if beyond_first_aid
            else "first_aid_only"
        ),
        inputs=inputs,
        sources=sources,
    )