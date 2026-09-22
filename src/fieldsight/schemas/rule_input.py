from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ConfidenceScore = Annotated[
    float,
    Field(
        ge=0.0,
        le=1.0,
        description="Confidence score between zero and one"
    )
]

EventType = Literal[
    "fatality",
    "inpatient_hospitalization",
    "amputation",
    "loss_of_eye",
    "other"
]

AdmissionReason = Literal[
    "care_or_treatment",
    "observation_only",
    "diagnostic_testing_only"
]

AmputationDetail = Literal[
    "traumatic_loss",
    "fingertip",
    "medical_amputation",
    "reattached_part",
    "avulsion",
    "enucleation",
    "degloving",
    "scalping",
    "severed_ear",
    "broken_tooth",
    "chipped_tooth"
]

class RuleInputs(BaseModel):
    """Base model for validated deterministic-rule inputs."""

    model_config = ConfigDict(extra="forbid")

class R1Inputs(RuleInputs):
    """Incident facts used to evaluate OSHA recordability."""

    work_related: bool | None = Field(
        default=None,
        description="Whether the injury or illness is work-related"
    )
    new_case: bool | None = Field(
        default=None,
        description="Whether the incident is a new case rather than a continuation of an existing case"
    )
    death: bool | None = Field(
        default=None,
        description="Whether the incident resulted in death"
    )
    days_away: int | None = Field(
        default=None,
        ge=0,
        description="Number of calendar days the employee was away from work"
    )
    restricted_days: int | None = Field(
        default=None,
        ge=0,
        description="Number of calendar days involving restricted work activity"
    )
    job_transfer: bool | None = Field(
        default=None,
        description="Whether the employee was transferred to another job because of the incident"
    )
    medical_treatment_beyond_first_aid: bool | None = Field(
        default=None,
        description="Whether R3 determined that treatment went beyond first aid"
    )
    loss_of_consciousness: bool | None = Field(
        default=None,
        description="Whether the employee lost consciousness"
    )
    significant_diagnosis: bool | None = Field(
        default=None,
        description="Whether a licensed healthcare professional diagnosed a significant injury or illness"
    )

class R2Inputs(RuleInputs):
    """Incident facts used to evaluate federal OSHA reporting requirements."""

    work_related: bool | None = Field(
        default=None,
        description="Whether the event resulted from a work-related incident"
    )
    event_type: EventType | None = Field(
        default=None,
        description="Type of severe event being evaluated"
    )
    incident_at: datetime | None = Field(
        default=None,
        description="Date and time when the work-related incident occurred"
    )
    event_at: datetime | None = Field(
        default=None,
        description="Date and time when the fatality, hospitalization, amputation or eye loss occurred"
    )
    learned_at: datetime | None = Field(
        default=None,
        description="Date and time when the employer learned that the event occurred and was work-related"
    )
    admission_reason: AdmissionReason | None = Field(
        default=None,
        description="Reason for an inpatient hospitalization when the event type is inpatient hospitalization"
    )
    amputation_detail: AmputationDetail | None = Field(
        default=None,
        description="Normalized injury category when the event type is amputation"
    )

class R3Inputs(RuleInputs):
    """Treatment facts used to distinguish first aid from medical treatment."""

    treatments: list[str] | None = Field(
        default=None,
        description="Normalized treatment identifiers extracted from the incident record"
    )

class R4Inputs(RuleInputs):
    """Facts used to select the OSHA 300 Log outcome column."""

    recordable: bool | None = Field(
        default=None,
        description="Whether R1 determined that the case is recordable"
    )
    death: bool | None = Field(
        default=None,
        description="Whether the incident resulted in death"
    )
    days_away: int | None = Field(
        default=None,
        ge=0,
        description="Number of calendar days away from work"
    )
    restricted_days: int | None = Field(
        default=None,
        ge=0,
        description="Number of calendar days involving restricted work activity"
    )
    job_transfer: bool | None = Field(
        default=None,
        description="Whether the incident resulted in a job transfer"
    )

class R5Inputs(RuleInputs):
    """Extraction confidence values used by the deterministic readiness gate."""

    confidences: dict[str, ConfidenceScore] = Field(
        description="Mapping from extracted field names to their confidence scores"
    )
    floor: ConfidenceScore = Field(
        default=0.60,
        description="Configured minimum acceptable extraction confidence"
    )