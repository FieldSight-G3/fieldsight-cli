from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from fieldsight.repository import IncidentRepository
from fieldsight.rules.engine import IncidentRuleResults, evaluate_incident
from fieldsight.schemas.incidents import NormalizedIncident

class AnalysisRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    results: IncidentRuleResults
    escalation_triggers: dict[str, Any] = Field(default_factory=dict)

def analyze_incident(incident_id: UUID) -> AnalysisRun:
    repository = IncidentRepository()
    stored = repository.get(incident_id)
    if stored is None:
        raise LookupError(f"Incident {incident_id} does not exist")
    facts = NormalizedIncident.model_validate({
        **stored.normalized_fields,
        "incident_id": str(stored.incident_id)
    })
    results = evaluate_incident(facts)
    triggers = escalation_triggers(facts, results)
    deciding_rule = "R1" if results.recordability is not None else "R5"
    run_id = repository.save_analysis(
        incident_id=incident_id,
        correlation_id=uuid4(),
        outcome=results.model_dump(mode="json"),
        deciding_rule=deciding_rule,
        rule_invocations=[invocation.model_dump(mode="json") for invocation in results.invocations],
        escalation_triggers=triggers
    )
    return AnalysisRun(run_id=run_id, results=results, escalation_triggers=triggers)

def escalation_triggers(incident: NormalizedIncident, results: IncidentRuleResults) -> dict[str, Any]:
    triggers: dict[str, Any] = {}
    if results.confidence.outcome != "ready":
        triggers["confidence_gate"] = results.confidence.model_dump(mode="json")
    if incident.death is True:
        triggers["fatality"] = {"field": "death"}
    if results.reporting is not None and results.reporting.outcome.startswith("reportable"):
        triggers["reportable_event"] = results.reporting.model_dump(mode="json")
    decisions = {
        "R5": results.confidence,
        "R3": results.treatment,
        "R1": results.recordability,
        "R2": results.reporting,
        "R4": results.log_classification
    }
    missing = [rule_id for rule_id, decision in decisions.items()
               if decision is not None and decision.outcome == "insufficient_data"]
    if missing:
        triggers["insufficient_data"] = {"rules": missing}
    return triggers
