""" the run record: every turn leaves one, refused or not, with the review queue row when escalation fired """

from uuid import UUID

from ...repository import IncidentRepository, RunRepository
from ...rules.engine import IncidentRuleResults
from ...schemas.incidents import NormalizedIncident
from ...schemas.run_records import RuleInvocation
from ...types.escalation import EscalationDecision
from ...types.run import WorkflowResult
from ..analysis import ReviewSnapshot


def _items(records: list) -> dict:
    """ the {"items": [...]} shape every run-record JSONB column uses; None stays None (a Reviewer with no verdict) """
    return {"items": [r.model_dump(mode="json") if r is not None else None for r in records]}


def save_run(correlation_id: UUID, command: str, incident: NormalizedIncident | None, *,
             results: IncidentRuleResults | None, decision: EscalationDecision | None,
             rule_invocations: list[RuleInvocation], workers: list[str] | None,
             workflow: WorkflowResult | None = None, review_snapshot: ReviewSnapshot | None = None,
             dossier: dict | None = None) -> UUID:
    """ one transaction when there's an incident; without one the row has no incident id, since it's a foreign key

        dossier is the one the turn showed (blocked legs withheld), kept so dossier and sources can read it later
    """

    recorded = [invocation.model_dump(mode="json") for invocation in rule_invocations]
    triggers = decision.model_dump(mode="json") if decision else None
    dispatched = {"items": workers} if workers is not None else None
    columns: dict = {}
    if workflow:
        dispatched = {"items": workers, "plans": workflow.plans}
        columns = {"tool_invocations": _items(workflow.tool_invocations),
                   "model_calls": _items(workflow.model_calls),
                   "reviewer_verdicts": _items(workflow.reviewer_verdicts)}
    if dossier is not None:
        columns["dossier"] = dossier
    if incident is None:
        return RunRepository().create(correlation_id, command, workers_dispatched=dispatched,
                                            rule_invocations={"items": recorded}, escalation_triggers=triggers)

    # only analyze writes the incident's outcome; an ask, even one re-running a rule on a hypothetical, never does
    outcome, deciding_rule = None, None
    if results and command == "analyze":
        outcome, deciding_rule = results.model_dump(mode="json"), "R1" if results.recordability is not None else "R5"
    if decision and decision.requires_review:
        # a queue row without the submitting analyst and the dossier as submitted can never be reviewed
        if review_snapshot is None:
            raise ValueError(f"Incident {incident.incident_id} escalates but the turn has no review snapshot")
        return IncidentRepository().save_analysis_for_review(
            UUID(incident.incident_id), correlation_id, outcome, deciding_rule, recorded, triggers,
            submitting_analyst_id=review_snapshot.submitting_analyst_id, dossier_snapshot=review_snapshot.dossier,
            citations=review_snapshot.citations, command=command, workers_dispatched=dispatched, **columns)
    return IncidentRepository().save_analysis(
        UUID(incident.incident_id), correlation_id, outcome, deciding_rule, recorded, triggers,
        requires_review=False, command=command, workers_dispatched=dispatched, **columns)