""" stage 4 on the dossier: every threshold outcome must match a rule invocation recorded this turn """

from ..rules.engine import evaluate_incident
from ..rules.proposal_review import review_classification, review_reporting
from ..schemas.incidents import NormalizedIncident
from ..schemas.rule_proposal import ClassificationProposal, ReportingProposal
from ..schemas.run_records import RuleInvocation
from ..types.dossier import Dossier
from ..types.guardrails import GuardrailEvent
from .common import DETERMINATION, citation_problems, emit, latest

# the propose tools' schemas and reviews, reused to check each leg against this turn's rule invocations
LEG_REVIEWS = {
    "recordability": (ClassificationProposal, review_classification),
    "reportability": (ReportingProposal, review_reporting),
}


def guard_dossier(dossier: Dossier, *, incident: NormalizedIncident | None, rule_invocations: list[RuleInvocation],
                  correlation_id: str) -> dict:
    """ the harness's own invocations are authoritative and win over the worker's tool-path decisions

        returns the blocked legs, each with what to fix for the Coordinator to re-dispatch,
        citations_supported for EscalationSignals, this turn's rule invocations, and the events
    """

    events: list[GuardrailEvent] = []
    invocations = list(rule_invocations)
    if not invocations and incident:
        invocations = evaluate_incident(incident).invocations
        emit(events, correlation_id, "output", "unattributed_threshold", "rule_run", "dossier")

    blocked: dict[str, list[str]] = {}
    citations_supported = True
    for worker, leg in dossier.items():
        if leg["proposal"] is None:
            continue
        proposal = leg["proposal"]
        _, unresolved = citation_problems(proposal["rationale"], proposal["chunk_ids"], set(leg["cited"]))
        citations_supported &= not unresolved
        problems = [f"{ref} doesn't cite a chunk retrieved this turn" for ref in unresolved]
        if worker in LEG_REVIEWS:
            schema, review = LEG_REVIEWS[worker]
            problems += review(schema.model_validate(proposal), {**leg["decisions"], **latest(invocations)}, set(leg["cited"]))
        if determination := DETERMINATION.search(proposal["rationale"]):
            problems.append(f'describe the regulation instead of concluding: "{determination.group()}"')
        if problems:
            blocked[worker] = problems
            emit(events, correlation_id, "output", "dossier_leg", "blocked", f"{worker}: {'; '.join(problems)}"[:200])
    return {"blocked": blocked, "citations_supported": citations_supported, "rule_invocations": invocations, "events": events}
