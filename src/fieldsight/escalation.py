"""Pure, auditable eligibility checks for incident review.

This module makes no model, AWS, or database calls. Callers supply the outcomes
of those stages as typed signals; an absent signal is recorded as unevaluated.
"""

from __future__ import annotations

from math import isclose
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fieldsight.rules.engine import IncidentRuleResults
from fieldsight.schemas.incidents import NormalizedIncident

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

    @model_validator(mode="after")
    def fired_checks_were_evaluated(self) -> TriggerEvaluation:
        if self.fired and not self.evaluated:
            raise ValueError("A trigger cannot fire before its signal is evaluated")
        return self


class EscalationDecision(BaseModel):
    """Full decision for a run record, including checks that did not fire."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requires_review: bool
    eligible_for_auto_release: bool
    fired: list[TriggerName]
    checks: dict[TriggerName, TriggerEvaluation]
    boundary_observations: list[BoundaryObservation]
    policy: EscalationPolicy


def evaluate_escalation(incident: NormalizedIncident,results: IncidentRuleResults,*,signals: EscalationSignals | None = None,policy: EscalationPolicy | None = None,) -> EscalationDecision:
    """Evaluate every named trigger without changing incident or rule results."""
    signals = signals if signals is not None else EscalationSignals()
    policy = policy if policy is not None else EscalationPolicy()
    checks: dict[TriggerName, TriggerEvaluation] = {}

    confidence = results.confidence
    checks["confidence_gate"] = TriggerEvaluation(
        evaluated=confidence.outcome != "insufficient_data",
        fired=confidence.outcome == "human_determination",
        reason_code=("below_confidence_floor" if confidence.outcome == "human_determination" else None),
        details=({"field": confidence.missing_field} if confidence.missing_field else {}),
    )

    decisions = (
        results.confidence,
        results.treatment,
        results.recordability,
        results.reporting,
        results.log_classification,
    )
    missing = [decision for decision in decisions if decision and decision.outcome == "insufficient_data"]
    checks["insufficient_data"] = TriggerEvaluation(
        evaluated=True,
        fired=bool(missing),
        reason_code="missing_rule_input" if missing else None,
        details={
            "rule_ids": ",".join(decision.rule_id for decision in missing),
            "fields": ",".join(decision.missing_field or "unknown" for decision in missing),
        } if missing else {},
    )

    boundaries = _boundary_observations(incident, results, policy)
    near = [boundary.name for boundary in boundaries if boundary.near]
    checks["near_boundary"] = TriggerEvaluation(
        evaluated=bool(boundaries),
        fired=bool(near),
        reason_code="near_rule_boundary" if near else None,
        details={"bounds": ",".join(near)} if near else {},
    )

    reviewer_fired = signals.reviewer_approved is False or (
        signals.reviewer_iterations is not None and signals.reviewer_iterations > 1
    )
    checks["reviewer"] = TriggerEvaluation(
        evaluated=signals.reviewer_approved is not None or reviewer_fired,
        fired=reviewer_fired,
        reason_code="reviewer_rejected_or_retried" if reviewer_fired else None,
        details=(
            {"iterations": signals.reviewer_iterations}
            if signals.reviewer_iterations is not None else {}
        ),
    )

    checks["citation"] = _boolean_check(
        signals.citations_supported,
        fired_when=False,
        reason_code="citation_missing_or_unsupported",
    )

    scores = signals.retrieval_scores
    retrieval_fired = scores is not None and (
        not scores or any(score < policy.retrieval_score_threshold for score in scores)
    )
    checks["retrieval"] = TriggerEvaluation(
        evaluated=scores is not None,
        fired=retrieval_fired,
        reason_code="no_retrieval_above_threshold" if retrieval_fired else None,
        details=(
            {"chunks": len(scores), "minimum_score": min(scores)}
            if scores else {"chunks": 0} if scores == [] else {}
        ),
    )

    checks["prompt_attack"] = _boolean_check(
        signals.prompt_attack_detected,
        fired_when=True,
        reason_code="prompt_attack_detected",
    )
    checks["fatality"] = _boolean_check(
        incident.death,
        fired_when=True,
        reason_code="fatality_requires_review",
    )

    report = results.reporting
    checks["reportable_event"] = TriggerEvaluation(
        evaluated=report is not None and report.outcome != "insufficient_data",
        fired=report is not None and report.outcome == "reportable",
        reason_code=(
            "osha_reportable_event" if report is not None and report.outcome == "reportable" else None
        ),
        details={"rule_id": "R2"} if report is not None else {},
    )
    checks["photo_contradiction"] = _boolean_check(
        signals.photo_contradicts,
        fired_when=True,
        reason_code="photo_contradicts_narrative",
    )

    fired: list[TriggerName] = [name for name, check in checks.items() if check.fired]
    return EscalationDecision(
        requires_review=bool(fired),
        eligible_for_auto_release=not fired and all(check.evaluated for check in checks.values()),
        fired=fired,
        checks=checks,
        boundary_observations=boundaries,
        policy=policy,
    )


def _boolean_check(
    value: bool | None,
    *,
    fired_when: bool,
    reason_code: str,
) -> TriggerEvaluation:
    fired = value is fired_when
    return TriggerEvaluation(
        evaluated=value is not None,
        fired=fired,
        reason_code=reason_code if fired else None,
    )


def _boundary_observations(
    incident: NormalizedIncident,
    results: IncidentRuleResults,
    policy: EscalationPolicy,
) -> list[BoundaryObservation]:
    observations: list[BoundaryObservation] = []
    floor = results.confidence.inputs.get("floor")
    if isinstance(floor, (float, int)) and incident.confidences:
        value = min(incident.confidences.values(), key=lambda score: abs(score - floor))
        observations.append(_observation(
            "confidence_0_60", value, float(floor), policy.confidence_margin_absolute, "confidence"
        ))

    if incident.work_related is True and incident.incident_at and incident.event_at:
        elapsed = incident.event_at - incident.incident_at
        if elapsed.total_seconds() >= 0:
            if incident.event_type == "fatality":
                observations.append(_observation(
                    "fatality_30d", elapsed.total_seconds() / 86400, 30.0,
                    policy.fatality_30d_margin_days, "days",
                ))
            elif incident.event_type in ("inpatient_hospitalization", "amputation", "loss_of_eye"):
                observations.append(_observation(
                    "reporting_24h", elapsed.total_seconds() / 3600, 24.0,
                    policy.reporting_24h_margin_hours, "hours",
                ))

    if (
        results.recordability is not None
        and results.recordability.outcome == "recordable"
        and incident.days_away is not None
        and incident.restricted_days is not None
    ):
        observations.append(_observation(
            "log_180d", float(incident.days_away + incident.restricted_days), 180.0,
            float(policy.log_180d_margin_days), "days",
        ))
    return observations


def _observation(
    name: BoundaryName,
    value: float,
    threshold: float,
    margin: float,
    unit: Literal["confidence", "hours", "days"],
) -> BoundaryObservation:
    return BoundaryObservation(
        name=name,
        value=value,
        threshold=threshold,
        margin=margin,
        unit=unit,
        near=(abs(value - threshold) <= margin or isclose(
            abs(value - threshold), margin, rel_tol=0.0, abs_tol=1e-12
        )),
    )
