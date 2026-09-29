""" the run record: every turn leaves one, refused or not, with the review queue row when escalation fired """

from uuid import UUID

from ...repository import IncidentRepository, RunRecordRepository
from ...rules.engine import IncidentRuleResults
from ...schemas.incidents import NormalizedIncident
from ...schemas.run_records import RuleInvocation
from ...types.escalation import EscalationDecision


def save_run(correlation_id: UUID, command: str, incident: NormalizedIncident | None, *,
             results: IncidentRuleResults | None, decision: EscalationDecision | None,
             rule_invocations: list[RuleInvocation], workers: list[str] | None) -> UUID:
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
    return IncidentRepository().save_analysis(
        UUID(incident.incident_id), correlation_id, outcome, deciding_rule, recorded, triggers,
        requires_review=bool(decision and decision.requires_review), command=command, workers_dispatched=dispatched)
