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
from fieldsight.rules.engine import IncidentRuleResults, evaluate_incident
from fieldsight.schemas.incidents import NormalizedIncident


class AnalysisRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    results: IncidentRuleResults
    escalation_decision: EscalationDecision
    escalation_triggers: dict[str, Any] = Field(default_factory=dict)


def analyze_incident(incident_id: UUID, *, signals: EscalationSignals | None = None) -> AnalysisRun:
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

    run_id = repository.save_analysis(
        incident_id=incident_id,
        correlation_id=uuid4(),
        outcome=results.model_dump(mode="json"),
        deciding_rule=deciding_rule,
        rule_invocations=[item.model_dump(mode="json") for item in results.invocations],
        escalation_triggers=decision.model_dump(mode="json"),
        requires_review=decision.requires_review,
    )
    return AnalysisRun(
        run_id=run_id,
        results=results,
        escalation_decision=decision,
        escalation_triggers=fired,
    )