from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from fieldsight.schemas.rule_input import (
    AdmissionReason,
    AmputationDetail,
    ConfidenceScore,
    EventType,
)


class NormalizedIncident(BaseModel):
    """Normalized incident facts produced from the submitted incident packet."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(
        description="Unique internal identifier for the incident"
    )
    work_related: bool | None = Field(
        description="Whether the incident is related to work"
    )
    new_case: bool | None = Field(
        description="Whether the incident is a new case"
    )
    incident_at: datetime | None = Field(
        description="Date and time when the workplace incident occurred"
    )
    event_at: datetime | None = Field(
        description="Date and time when the severe outcome occurred"
    )
    learned_at: datetime | None = Field(
        description="Date and time when the employer learned about the event and its work relationship"
    )
    event_type: EventType | None = Field(
        description="Normalized severe-event category"
    )
    admission_reason: AdmissionReason | None = Field(
        description="Reason for hospital admission when hospitalization occurred"
    )
    amputation_detail: AmputationDetail | None = Field(
        description="Normalized amputation or excluded-injury category"
    )
    treatments: list[str] | None = Field(
        description="Normalized treatments given to the employee"
    )
    death: bool | None = Field(
        description="Whether the employee died"
    )
    days_away: int | None = Field(
        ge=0,
        description="Number of calendar days away from work"
    )
    restricted_days: int | None = Field(
        ge=0,
        description="Number of calendar days involving restricted work"
    )
    job_transfer: bool | None = Field(
        description="Whether the employee was transferred to another job"
    )
    loss_of_consciousness: bool | None = Field(
        description="Whether the employee lost consciousness"
    )
    significant_diagnosis: bool | None = Field(
        description="Whether a licensed healthcare professional made a significant diagnosis"
    )
    confidences: dict[str, ConfidenceScore] = Field(
        description="Confidence score for each extracted incident field"
    )