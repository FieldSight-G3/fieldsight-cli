from datetime import datetime, timezone

from fieldsight.rules.confidence import confidence_floor
from fieldsight.rules.log_classification import log_classification
from fieldsight.rules.recordability import recordability
from fieldsight.rules.reporting import reporting_clock
from fieldsight.rules.treatment import medical_treatment
from fieldsight.schemas.rule_input import (
    R1Inputs,
    R2Inputs,
    R3Inputs,
    R4Inputs,
    R5Inputs,
)


def main() -> None:
    # R3: Was treatment beyond first aid?
    r3 = medical_treatment(
        R3Inputs(
            treatments=["prescription_medication"],
        )
    )
    # R1: Is the incident recordable?
    r1 = recordability(
    R1Inputs(
        work_related=True,
        new_case=True,
        death=False,
        days_away=30,
        restricted_days=0,
        job_transfer=False,
        medical_treatment_beyond_first_aid=(
            r3.outcome == "beyond_first_aid"
        ),
        loss_of_consciousness=False,
        significant_diagnosis=False,
    )
    )
    r4 = log_classification(
        R4Inputs(
            recordable=r1.outcome == "recordable",
            death=False,
            days_away=30,
            restricted_days=0,
            job_transfer=False,
        )
    )
    # R2: Is the event reportable, and what is the deadline?
    incident_at = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    hospitalization_at = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
    learned_at = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)

    r2 = reporting_clock(
        R2Inputs(
            work_related=True,
            event_type="inpatient_hospitalization",
            incident_at=incident_at,
            event_at=hospitalization_at,
            learned_at=learned_at,
            admission_reason="care_or_treatment",
        )
    )
    # R5: Are all confidence scores acceptable?
    r5 = confidence_floor(
        R5Inputs(
            confidences={
                "event_type": 0.98,
                "learned_at": 0.93,
                "days_away": 0.91,
                "treatments": 0.88,
            },
            floor=0.60,
        )
    )
    print("R3:", r3.model_dump_json(indent=2))
    print("R1:", r1.model_dump_json(indent=2))
    print("R2:", r2.model_dump_json(indent=2))
    print("R4:", r4.model_dump_json(indent=2))
    print("R5:", r5.model_dump_json(indent=2))


if __name__ == "__main__":
    main()