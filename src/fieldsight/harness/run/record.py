""" the run record: every turn leaves one, refused or not, with the review queue row when escalation fired """

from uuid import UUID

from ...repository import IncidentRepository, RunRecordRepository
from ...rules.engine import IncidentRuleResults
from ...schemas.incidents import NormalizedIncident
from ...schemas.run_records import RuleInvocation
from ...types.escalation import EscalationDecision
from ...types.run import WorkflowResult


def _items(records: list) -> dict:
    """ the {"items": [...]} shape every run-record JSONB column uses; None stays None (a Reviewer with no verdict) """
    return {"items": [r.model_dump(mode="json") if r is not None else None for r in records]}

def save_run(correlation_id: UUID, command: str, incident: NormalizedIncident | None, *,
             results: IncidentRuleResults | None, decision: EscalationDecision | None,
             rule_invocations: list[RuleInvocation], workers: list[str] | None, workflow: WorkflowResult | None = None) -> UUID:
    """ one transaction when there's an incident; without one the row has no incident id, since it's a foreign key """

    recorded = [invocation.model_dump(mode="json") for invocation in rule_invocations]
    triggers = decision.model_dump(mode="json") if decision else None
    dispatched = {"items": workers} if workers is not None else None
    columns: dict = {}
    if workflow:
        dispatched = {"items": workers, "plans": workflow.plans}
        columns = {"tool_invocations": _items(workflow.tool_invocations),
                   "model_calls": _items(workflow.model_calls),
                   "reviewer_verdicts": _items(workflow.reviewer_verdicts)}
        if snapshot := workflow.review_snapshot:
            dumped = snapshot.model_dump(mode="json")
            columns["review"] = {"submitting_analyst_id": snapshot.submitting_analyst_id,
                                 "dossier_snapshot": dumped["dossier"], "citations": dumped["citations"]}
    if incident is None:
        return RunRecordRepository().create(correlation_id, command, workers_dispatched=dispatched,
                                            rule_invocations={"items": recorded}, escalation_triggers=triggers)

    # only analyze writes the incident's outcome; an ask, even one re-running a rule on a hypothetical, never does
    outcome, deciding_rule = None, None
    if results and command == "analyze":
        outcome, deciding_rule = results.model_dump(mode="json"), "R1" if results.recordability is not None else "R5"
    return IncidentRepository().save_analysis(
        UUID(incident.incident_id), correlation_id, outcome, deciding_rule, recorded, triggers,
        requires_review=bool(decision and decision.requires_review), command=command, workers_dispatched=dispatched, **columns)
