""" the run record: every turn leaves one, refused or not, with the review queue row when escalation fired """

from uuid import UUID

from ...repository import IncidentRepository, RunRepository
from ...rules.engine import IncidentRuleResults
from ...schemas.incidents import NormalizedIncident
from ...schemas.run_records import ModelCall, RuleInvocation
from ...types.escalation import EscalationDecision
from ...types.run import WorkflowResult
from ..escalation.snapshot import ReviewSnapshot
from ..metering.meter import ModelCall as MeteredCall


def _items(records: list) -> dict:
    """ the {"items": [...]} shape every run-record JSONB column uses; None stays None (a Reviewer with no verdict) """
    return {"items": [r.model_dump(mode="json") if r is not None else None for r in records]}


def metered_calls(agent: str, calls: list[MeteredCall]) -> dict:
    """ the turn meter's priced calls in the run record's model-call shape, for prompted calls made outside the graph """
    return _items([ModelCall(agent=agent, model_id=call.model_id, input_tokens=call.input_tokens,
                             output_tokens=call.output_tokens, latency_ms=round(call.seconds * 1000), cost_usd=call.cost_usd)
                   for call in calls])


def save_run(correlation_id: UUID, command: str, incident: NormalizedIncident | None, *,
             results: IncidentRuleResults | None, decision: EscalationDecision | None,
             rule_invocations: list[RuleInvocation], workers: list[str] | None,
             workflow: WorkflowResult | None = None, review_snapshot: ReviewSnapshot | None = None,
             dossier: dict | None = None, metered: list[MeteredCall] | None = None) -> UUID:
    """ one transaction when there's an incident; without one the row has no incident id, since it's a foreign key

        dossier is the one the turn showed (blocked legs withheld), kept so dossier and sources can read it later;
        metered is the turn meter's calls, recorded when the graph didn't run (the readiness and answer calls of an ask)
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
    elif metered:
        # the graph records its own calls from its transcripts; without it, the meter has every prompted call
        columns["model_calls"] = metered_calls(command, metered)
    if dossier is not None:
        columns["dossier"] = dossier
    if incident is None:
        return RunRepository().create(correlation_id, command, workers_dispatched=dispatched,
                                      rule_invocations={"items": recorded}, escalation_triggers=triggers,
                                      model_calls=columns.get("model_calls"))

    # only analyze writes the incident's outcome; an ask, even one re-running a rule on a hypothetical, never does
    outcome, deciding_rule = None, None
    if results and command == "analyze":
        outcome, deciding_rule = results.model_dump(mode="json"), "R1" if results.recordability is not None else "R5"
    # a queue row without the submitting analyst and the dossier as submitted can never be reviewed
    if decision and decision.requires_review and review_snapshot is None:
        raise ValueError(f"Incident {incident.incident_id} escalates but the turn has no review snapshot")
    return IncidentRepository().save_analysis(
        UUID(incident.incident_id), correlation_id, outcome, deciding_rule, recorded, triggers,
        review=review_snapshot, command=command, workers_dispatched=dispatched, **columns)