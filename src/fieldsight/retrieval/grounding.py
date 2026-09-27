""" keep grounded answers; refuse the rest with what was searched and where to escalate """

import logging

from ..schemas.retrieval import (
    Citation,
    DraftAnswer,
    GroundedAnswer,
    RefusalReason,
    Retrieval,
)
from .corpus import meta

log = logging.getLogger(__name__)

ESCALATION = "Route this question to a human analyst through the review queue (fieldsight queue)."

PROBLEMS: dict[RefusalReason, str] = {
    "below_threshold": "No passage in the regulatory corpus scored above the similarity threshold.",
    "retrieval_unavailable": "The regulatory corpus couldn't be searched, so nothing can be grounded.",
    "not_grounded": "The retrieved passages don't answer this question.",
    "unresolved_citation": "The answer cited passages that weren't retrieved, so it can't be trusted.",
}


def searched(retrievals: list[Retrieval]) -> list[str]:
    """ each search's scope, in words """

    return [" ".join(part for part in (r.doc_type, r.section_path and f"section {r.section_path}") if part)
            or "the whole corpus" for r in retrievals] or ["the whole corpus"]


def any_below(retrievals: list[Retrieval]) -> bool:
    """ escalation trigger: a live search found nothing above threshold """

    return any(not r.scores for r in retrievals if not r.superseded)


def refuse(evidence: dict, reason: RefusalReason | None = None, detail: str = "") -> GroundedAnswer:
    """ refusal naming the searches and where to escalate; logged to surface corpus gaps """

    reason = reason or evidence["refusal"]
    scopes = searched(evidence["retrievals"])
    message = (f'{PROBLEMS[reason]}{detail} Searched {"; ".join(scopes)} for "{evidence["question"]}". '
               f"FieldSight won't answer from model knowledge. {ESCALATION}")
    log.warning("retrieval refused", extra={"reason": reason, "question": evidence["question"], "searched": scopes})
    return GroundedAnswer(
        question=evidence["question"], answer=message, grounded=False, refusal_reason=reason, searched=scopes,
        escalation=ESCALATION, below_threshold_anywhere=reason == "below_threshold" or any_below(evidence["retrievals"]),
        retrievals=evidence["retrievals"])


def enforce_grounding(evidence: dict) -> GroundedAnswer:
    """ keep the answer only if the model says it's grounded and every cited chunk was retrieved """

    draft: DraftAnswer = evidence["draft"]
    retrieved = {meta(doc)["chunk_id"]: meta(doc) for doc in evidence["docs"]}
    if not draft.grounded or not draft.chunk_ids:
        return refuse(evidence, "not_grounded", f" The model said: {draft.answer}")
    unresolved = [chunk_id for chunk_id in draft.chunk_ids if chunk_id not in retrieved]
    if unresolved:
        return refuse(evidence, "unresolved_citation", f" Unresolved: {', '.join(unresolved)}.")

    sources = [Citation(**{key: retrieved[chunk_id][key] for key in ("doc_id", "title", "section_path", "chunk_id")})
               for chunk_id in draft.chunk_ids]
    return GroundedAnswer(
        question=evidence["question"], answer=draft.answer, grounded=True, sources=sources,
        searched=searched(evidence["retrievals"]), below_threshold_anywhere=any_below(evidence["retrievals"]),
        retrievals=evidence["retrievals"])
