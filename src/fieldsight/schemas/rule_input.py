from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


ConfidenceScore = Annotated[float, Field(ge=0.0, le=1.0)]

EventType = Literal[
    "fatality",
    "inpatient_hospitalization",
    "amputation",
    "loss_of_eye",
    "other",
]

AdmissionReason = Literal[
    "care_or_treatment",
    "observation_only",
    "diagnostic_testing_only",
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
    "chipped_tooth",
]


class RuleInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class R1Inputs(RuleInputs):
    work_related: bool | None = None
    new_case: bool | None = None
    death: bool | None = None
    days_away: int | None = Field(default=None, ge=0)
    restricted_days: int | None = Field(default=None, ge=0)
    job_transfer: bool | None = None
    medical_treatment_beyond_first_aid: bool | None = None
    loss_of_consciousness: bool | None = None
    significant_diagnosis: bool | None = None


class R2Inputs(RuleInputs):
    work_related: bool | None = None
    event_type: EventType | None = None
    incident_at: datetime | None = None
    event_at: datetime | None = None
    learned_at: datetime | None = None
    admission_reason: AdmissionReason | None = None
    amputation_detail: AmputationDetail | None = None


class R3Inputs(RuleInputs):
    treatments: list[str] | None = None


class R4Inputs(RuleInputs):
    recordable: bool | None = None
    death: bool | None = None
    days_away: int | None = Field(default=None, ge=0)
    restricted_days: int | None = Field(default=None, ge=0)
    job_transfer: bool | None = None


class R5Inputs(RuleInputs):
    confidences: dict[str, ConfidenceScore]
    floor: ConfidenceScore = 0.60