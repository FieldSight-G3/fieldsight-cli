""" keep grounded answers; refuse the rest with what was searched and where to escalate """

import logging
import re

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

# a citation in an answer, [n]
CITATION = re.compile(r"\[(\d+)\]")


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


# a citation written as the chunk id itself, e.g. [CFR-1904-d6bf67b0d2f6] or [CFR-1904-..., CPL-172-...]
CHUNK_ID = r"[A-Z][A-Z0-9-]*-[0-9a-f]{3,12}"
CITED_BY_ID = re.compile(rf"\[\s*({CHUNK_ID}(?:\s*,\s*{CHUNK_ID})*)\s*\]")


def by_position(draft: DraftAnswer, retrieved: dict[str, dict]) -> DraftAnswer:
    """ the draft with its chunk ids resolved to retrieved chunks and each citation as its [n] position

        The model sometimes cites [CFR-1904-d6bf67b0d2f6] instead of [1], or lists an id cut short
        (CFR-1904-7b6). Both were refused as unresolved although the chunk was retrieved this turn. A shortened id
        resolves only when exactly one retrieved chunk starts with it; anything else is left for the checks.
    """

    def resolve(chunk_id: str) -> str:
        if chunk_id in retrieved:
            return chunk_id
        matches = [known for known in retrieved if known.startswith(chunk_id)]
        return matches[0] if len(matches) == 1 else chunk_id

    chunk_ids = [resolve(chunk_id) for chunk_id in draft.chunk_ids]

    def position(match: re.Match) -> str:
        ids = [resolve(chunk_id.strip()) for chunk_id in match.group(1).split(",")]
        if not all(chunk_id in chunk_ids or chunk_id in retrieved for chunk_id in ids):
            return match.group(0)
        for chunk_id in ids:
            if chunk_id not in chunk_ids:
                chunk_ids.append(chunk_id)
        return "".join(f"[{chunk_ids.index(chunk_id) + 1}]" for chunk_id in ids)

    return draft.model_copy(update={"answer": CITED_BY_ID.sub(position, draft.answer), "chunk_ids": chunk_ids})


def enforce_grounding(evidence: dict) -> GroundedAnswer:
    """ keep the answer only if the model says it's grounded and every cited chunk was retrieved """

    draft: DraftAnswer | None = evidence["draft"]
    retrieved = {meta(doc)["chunk_id"]: meta(doc) for doc in evidence["docs"]}
    if draft is None:
        # the model answered in prose instead of the structured draft: nothing it said can be checked
        return refuse(evidence, "not_grounded", " The model returned no structured answer.")
    draft = by_position(draft, retrieved)
    cited = [int(n) for n in CITATION.findall(draft.answer)]
    if cited and len(draft.chunk_ids) < max(cited) <= len(evidence["docs"]):
        # the model numbered its citations by the excerpts as shown, not by its own chunk_ids list
        draft = draft.model_copy(update={"chunk_ids": [meta(doc)["chunk_id"] for doc in evidence["docs"]]})
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
