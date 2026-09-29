""" the eligibility check: score the reviewed dossier and, if it escalates, queue it with a frozen snapshot for a human """

from uuid import UUID

from ...harness.analysis import ReviewSnapshot, analyze_incident
from ...harness.escalation.review import CitationReference
from ...types.escalation import EscalationSignals


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
    """ run the rules and escalation policy on the incident; route_after_review sends every finished cycle here """

    reviews = state.get("reviews") or []
    if not reviews:
        approved = None
    else:
        # no verdict counts as not approved, as in route_after_review
        approved = reviews[-1] is not None and reviews[-1].approved
    signals = EscalationSignals(
        reviewer_approved=approved,
        reviewer_iterations=state.get("review_iterations"),
        citations_supported=state.get("citations_supported"),
    )
    run = analyze_incident(UUID(str(state["incident"]["incident_id"])), signals=signals, review_snapshot=review_snapshot(state))
    return {"analysis_run_id": str(run.run_id), "requires_review": run.escalation_decision.requires_review}
