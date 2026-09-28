""" shapes of the escalation check: the signals other stages hand it, and the decision it records """

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Score = Annotated[float, Field(ge=0.0, le=1.0)]
TriggerName = Literal[
    "confidence_gate",
    "insufficient_data",
    "near_boundary",
    "reviewer",
    "citation",
    "retrieval",
    "prompt_attack",
    "fatality",
    "reportable_event",
    "photo_contradiction",
]
BoundaryName = Literal["confidence_0_60", "reporting_24h", "fatality_30d", "log_180d"]


class EscalationPolicy(BaseModel):
    """Named margins in the same units as their rule boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confidence_margin_absolute: Score = 0.02
    reporting_24h_margin_hours: float = Field(default=1.0, ge=0.0)
    fatality_30d_margin_days: float = Field(default=1.0, ge=0.0)
    log_180d_margin_days: int = Field(default=1, ge=0)
    retrieval_score_threshold: Score = 0.60


class EscalationSignals(BaseModel):
    """Results computed by other stages, never a model's self-reported confidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reviewer_approved: bool | None = None
    reviewer_iterations: int | None = Field(default=None, ge=0)
    citations_supported: bool | None = None
    retrieval_scores: list[Score] | None = None
    prompt_attack_detected: bool | None = None
    photo_contradicts: bool | None = None


class BoundaryObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: BoundaryName
    value: float
    threshold: float
    margin: float
    unit: Literal["confidence", "hours", "days"]
    near: bool


class TriggerEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluated: bool
    fired: bool
    reason_code: str | None = None
    details: dict[str, str | int | float | bool] = Field(default_factory=dict)


class EscalationDecision(BaseModel):
    """Full decision for a run record, including checks that did not fire."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requires_review: bool
    eligible_for_auto_release: bool
    fired: list[TriggerName]
    checks: dict[TriggerName, TriggerEvaluation]
    boundary_observations: list[BoundaryObservation]
    policy: EscalationPolicy
