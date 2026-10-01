""" gather evidence for a question: first search, fallback, and second hops, each recorded """

from concurrent.futures import ThreadPoolExecutor
from typing import get_args

from langchain_core.documents import Document

from ..errors import RetrievalError
from ..schemas.retrieval import RefusalReason, Retrieval
from ..types.corpus import DocType
from .corpus import meta, search
from .references import hop_targets, pick_filter

# a hop's best chunks from the section a retrieved chunk cites
HOP_CHUNKS = 3


def run(query: str, retrievals: list[Retrieval], doc_type: DocType | None = None,
        section_path: str | None = None, reason: str = "the question", gated: bool = True,
        limit: int | None = None) -> list[Document]:
    """ run one search, recording each chunk id and score it keeps """

    docs = search(query, doc_type=doc_type, section_path=section_path, gated=gated)[:limit]
    retrievals.append(Retrieval(query=query, doc_type=doc_type, section_path=section_path, reason=reason,
                                scores={meta(doc)["chunk_id"]: doc.metadata["score"] for doc in docs}))
    return docs


def follow_references(question: str, docs: list[Document], retrievals: list[Retrieval]) -> list[Document]:
    """ first-search chunks plus their second hops, deduplicated by chunk id

        The first search's threshold decides whether the corpus covers the question at all. A hop is relevant because
        a retrieved chunk cites its section, not because the question resembles it: a regulation's formal text scores
        below the commentary that cites it, so the gate would drop the very provision being cited. A hop takes the
        cited section's best chunks instead.
    """

    for hop in hop_targets(question, docs):
        docs = docs + run(hop.query, retrievals, hop.doc_type, hop.section_path, hop.reason, gated=False, limit=HOP_CHUNKS)
    unique: dict[str, Document] = {}
    for doc in docs:
        unique.setdefault(meta(doc)["chunk_id"], doc)
    return list(unique.values())


def diversify(question: str, docs: list[Document], retrievals: list[Retrieval]) -> list[Document]:
    """ an unfiltered search's chunks plus the best one of each document type it returned none of

        Each kind of document carries its own authority: the regulation states the rule, the preamble why, the
        directive how OSHA enforces it, and the letters answer the edge cases. A whole-corpus top-k can fill with one
        kind and crowd out the letter that decides the question, so each type's best chunk above the threshold
        joins the evidence. A type with none above it adds nothing, and its search is recorded as superseded: the
        main search's coverage stands.
    """

    present = {meta(doc)["doc_type"] for doc in docs}
    missing = [doc_type for doc_type in get_args(DocType) if doc_type not in present]
    with ThreadPoolExecutor(max_workers=len(missing) or 1) as pool:
        found = list(pool.map(lambda doc_type: search(question, doc_type=doc_type), missing))
    for doc_type, hits in zip(missing, found):
        best = hits[:1]
        retrievals.append(Retrieval(query=question, doc_type=doc_type, reason=f"the best {doc_type} chunk for the question",
                                    scores={meta(doc)["chunk_id"]: doc.metadata["score"] for doc in best},
                                    superseded=not best))
        docs = docs + best
    return docs


# a letter of interpretation is short; the most chunks one spans in the corpus
LETTER_CHUNKS = 9


def whole_letters(question: str, docs: list[Document], retrievals: list[Retrieval]) -> list[Document]:
    """ every retrieved letter of interpretation in full

        A letter states the question it was asked, then OSHA's answer, and chunking splits the two: the chunk that
        matches a question is often the letter's restatement of it, while the answer sits in the next chunk. So a
        retrieved letter chunk brings the rest of its letter (its section is the letter's date).
    """

    letters = sorted({meta(doc)["section_path"] for doc in docs if meta(doc)["doc_type"] == "interpretation"})
    for letter in letters:
        docs = docs + run(question, retrievals, "interpretation", letter, f"the rest of the {letter} letter", gated=False,
                          limit=LETTER_CHUNKS)
    unique: dict[str, Document] = {}
    for doc in docs:
        unique.setdefault(meta(doc)["chunk_id"], doc)
    return list(unique.values())


def gather(inputs: dict) -> dict:
    """ chunks for a question, the searches behind them, and a refusal reason if there are none """

    question = inputs["question"]
    retrievals: list[Retrieval] = []
    doc_type, section_path, reason = pick_filter(question)
    try:
        docs = run(question, retrievals, doc_type, section_path, reason)
        if not docs and (doc_type or section_path):
            retrievals[0] = retrievals[0].model_copy(update={"superseded": True})
            docs = run(question, retrievals, reason="the filtered search found nothing above threshold")
        if docs and retrievals[-1].doc_type is None and retrievals[-1].section_path is None:
            docs = diversify(question, docs, retrievals)
        if docs:
            docs = whole_letters(question, follow_references(question, docs, retrievals), retrievals)
        refusal: RefusalReason | None = None if docs else "below_threshold"
    except RetrievalError:
        docs, refusal = [], "retrieval_unavailable"
    # anything else the caller passed (a regeneration's objections) rides along to the prompt, never the search
    return {**inputs, "question": question, "docs": docs, "retrievals": retrievals, "refusal": refusal}
