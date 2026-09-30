""" the eligibility check: stage 4 (guard_dossier) on the reviewed dossier, and the snapshot a reviewer would need; run_turn escalates and writes """

from datetime import UTC, datetime
from uuid import UUID

from ...harness.analysis import ReviewSnapshot
from ...harness.escalation.review import CitationReference
from ...harness.guardrails.dossier_guard import guard_dossier
from ...schemas.incidents import NormalizedIncident
from ...schemas.run_records import RuleInvocation


def review_snapshot(state: dict) -> ReviewSnapshot:
    """ the dossier the Reviewer saw, with every cited chunk mapped to its source document; keyed by chunk id """

    citations = {
        chunk_id: CitationReference(document_id=hit["doc_id"], chunk_id=chunk_id)
        for leg in state["dossier"].values()
        for chunk_id, hit in leg["cited"].items()
    }
    return ReviewSnapshot(
        submitting_analyst_id=UUID(str(state["analyst_id"])),
        dossier=state["dossier"],
        citations=citations,
    )


def eligibility_check_node(state: dict) -> dict:
    """ stage 4 on the reviewed dossier; escalation and the run record happen in run_turn once the graph returns """

    incident = NormalizedIncident.model_validate(state["incident"])
    dossier = state.get("dossier") or {}
    # the workers' own evaluate_rule results; §6 says the tool path records an invocation too
    worker_rules = [RuleInvocation(incident_id=incident.incident_id, recorded_at=datetime.now(UTC), decision=decision)
                    for leg in dossier.values() for decision in leg["decisions"].values()]
    guard = guard_dossier(dossier, incident=incident, rule_invocations=worker_rules,
                          correlation_id=state["correlation_id"])
    return {**guard, "review_snapshot": review_snapshot({**state, "dossier": dossier})}