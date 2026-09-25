""" gather evidence for a question: first search, fallback, and second hops, each recorded """

from langchain_core.documents import Document

from ..errors import RetrievalError
from ..schemas.retrieval import RefusalReason, Retrieval
from ..types.corpus import DocType
from .corpus import meta, search
from .references import hop_targets, pick_filter


def run(query: str, retrievals: list[Retrieval], doc_type: DocType | None = None,
        section_path: str | None = None, reason: str = "the question") -> list[Document]:
    """ run one search, recording each chunk id and score """

    docs = search(query, doc_type=doc_type, section_path=section_path)
    retrievals.append(Retrieval(query=query, doc_type=doc_type, section_path=section_path, reason=reason,
                                scores={meta(doc)["chunk_id"]: doc.metadata["score"] for doc in docs}))
    return docs


def follow_references(question: str, docs: list[Document], retrievals: list[Retrieval]) -> list[Document]:
    """ first-search chunks plus their second hops, deduplicated by chunk id """

    for hop in hop_targets(question, docs):
        docs = docs + run(hop.query, retrievals, hop.doc_type, hop.section_path, hop.reason)
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
        if docs:
            docs = follow_references(question, docs, retrievals)
        refusal: RefusalReason | None = None if docs else "below_threshold"
    except RetrievalError:
        docs, refusal = [], "retrieval_unavailable"
    return {"question": question, "docs": docs, "retrievals": retrievals, "refusal": refusal}
