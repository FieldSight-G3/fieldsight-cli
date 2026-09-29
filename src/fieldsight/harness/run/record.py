""" the run record: every turn leaves one, refused or not, with the review queue row when escalation fired """

from uuid import UUID

from ...repository import IncidentRepository, RunRecordRepository
from ...rules.engine import IncidentRuleResults
from ...schemas.incidents import NormalizedIncident
from ...schemas.run_records import RuleInvocation
from ...types.escalation import EscalationDecision
from ..analysis import ReviewSnapshot


def save_run(correlation_id: UUID, command: str, incident: NormalizedIncident | None, *,
             results: IncidentRuleResults | None, decision: EscalationDecision | None,
             rule_invocations: list[RuleInvocation], workers: list[str] | None,
             review_snapshot: ReviewSnapshot | None = None) -> UUID:
    """ one transaction when there's an incident; without one the row has no incident id, since it's a foreign key """

    recorded = [invocation.model_dump(mode="json") for invocation in rule_invocations]
    triggers = decision.model_dump(mode="json") if decision else None
    dispatched = {"items": workers} if workers is not None else None
    if incident is None:
        return RunRecordRepository().create(correlation_id, command, workers_dispatched=dispatched,
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
            citations=review_snapshot.citations, command=command, workers_dispatched=dispatched)
    return IncidentRepository().save_analysis(
        UUID(incident.incident_id), correlation_id, outcome, deciding_rule, recorded, triggers,
        requires_review=False, command=command, workers_dispatched=dispatched)
