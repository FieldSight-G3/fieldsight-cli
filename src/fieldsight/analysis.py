from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from fieldsight.escalation import (
    EscalationDecision,
    EscalationSignals,
    evaluate_escalation,
)
from fieldsight.repository import IncidentRepository
from fieldsight.review_decisions import CitationReference
from fieldsight.rules.engine import IncidentRuleResults, evaluate_incident
from fieldsight.schemas.incidents import NormalizedIncident


class ReviewSnapshot(BaseModel):
    """The dossier as submitted, frozen onto the review queue row if the case escalates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    submitting_analyst_id: UUID
    dossier: dict[str, Any]
    citations: dict[str, CitationReference]


class AnalysisRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    results: IncidentRuleResults
    escalation_decision: EscalationDecision
    escalation_triggers: dict[str, Any] = Field(default_factory=dict)


def analyze_incident(incident_id: UUID, *, signals: EscalationSignals | None = None, review_snapshot: ReviewSnapshot | None = None) -> AnalysisRun:
    repository = IncidentRepository()
    stored = repository.get(incident_id)
    if stored is None:
        raise LookupError(f"Incident {incident_id} does not exist")

    facts = NormalizedIncident.model_validate({
        **stored.normalized_fields,
        "incident_id": str(stored.incident_id),
    })
    results = evaluate_incident(facts)
    decision = evaluate_escalation(facts, results, signals=signals)
    fired = {name: decision.checks[name].model_dump(mode="json") for name in decision.fired}
    deciding_rule = "R1" if results.recordability is not None else "R5"

    analysis = {
        "incident_id": incident_id,
        "correlation_id": uuid4(),
        "outcome": results.model_dump(mode="json"),
        "deciding_rule": deciding_rule,
        "rule_invocations": [item.model_dump(mode="json") for item in results.invocations],
        "escalation_triggers": decision.model_dump(mode="json"),
    }
    if decision.requires_review:
        if review_snapshot is None:
            # a queue row without a snapshot can never be reviewed; even a no-dossier case needs its submitter
            raise ValueError(f"Incident {incident_id} escalates ({', '.join(decision.fired)}) but no review snapshot was given")
        run_id = repository.save_analysis_for_review(
            **analysis,
            submitting_analyst_id=review_snapshot.submitting_analyst_id,
            dossier_snapshot=review_snapshot.dossier,
            citations=review_snapshot.citations,
        )
    else:
        run_id = repository.save_analysis(**analysis, requires_review=False)
    return AnalysisRun(
        run_id=run_id,
        results=results,
        escalation_decision=decision,
        escalation_triggers=fired,
    )