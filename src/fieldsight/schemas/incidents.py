from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: object
    confidence: float = Field(ge=0.0, le=1.0)
    source_artifact: str


class NormalizedIncident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    work_related: bool | None
    new_case: bool | None

    incident_at: datetime | None
    event_at: datetime | None
    learned_at: datetime | None

    event_type: str | None
    admission_reason: str | None
    amputation_detail: str | None

    treatments: list[str] | None

    death: bool | None
    days_away: int | None
    restricted_days: int | None
    job_transfer: bool | None
    loss_of_consciousness: bool | None
    significant_diagnosis: bool | None

    confidences: dict[str, float]