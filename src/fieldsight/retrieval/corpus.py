""" the corpus KB as a retriever: top-k hits above the score threshold, optionally filtered by metadata

    The corpus KB is a Bedrock-managed KB, whose scores are relative to each query (its best hit scores near 1.0
    even for a question the corpus can't answer), so they can't gate a refusal. Each hit is rescored here as the
    cosine similarity of its Titan v2 embedding to the query's, the same model the KB indexes with, and the
    threshold gates on that.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from ..aws import clients
from ..aws.errors import raises
from ..config import settings
from ..errors import RetrievalError


def kb_filter(doc_type: str | None, section_path: str | None) -> dict | None:
    """ KB filter for whichever of doc_type and section_path are given """

    conditions = [{"equals": {"key": key, "value": value}} for key, value in (("doc_type", doc_type), ("section_path", section_path)) if value]
    if len(conditions) > 1:
        return {"andAll": conditions}
    return conditions[0] if conditions else None


def meta(hit: Document) -> dict:
    """ our chunk metadata on a KB hit """

    return hit.metadata["source_metadata"]


def build_retriever(doc_type: str | None = None, section_path: str | None = None) -> BaseRetriever:
    """ corpus KB retriever, optionally filtered; ungated, because search gates on its own score """

    return clients.corpus_retriever(kb_filter(doc_type, section_path))


@lru_cache(maxsize=2048)
def chunk_vector(chunk_id: str, text: str) -> tuple[float, ...]:
    """ a chunk's Titan v2 embedding; chunk ids are stable, so each chunk is embedded once per process """

    return tuple(clients.embeddings().embed_query(text))


def rescore(query_vector: list[float], hits: list[Document]) -> list[Document]:
    """ hits scored by cosine similarity to the query's embedding, best first; the KB's own score is kept as kb_score """

    if not hits:
        return []
    with ThreadPoolExecutor(max_workers=len(hits)) as pool:
        vectors = list(pool.map(lambda hit: chunk_vector(meta(hit)["chunk_id"], hit.page_content), hits))
    for hit, vector in zip(hits, vectors):
        # both vectors are unit length, so the dot product is the cosine; unrelated text can dip below zero
        similarity = sum(a * b for a, b in zip(query_vector, vector))
        hit.metadata["kb_score"] = hit.metadata.get("score")
        hit.metadata["score"] = max(0.0, similarity)
    return sorted(hits, key=lambda hit: hit.metadata["score"], reverse=True)


@raises(RetrievalError, "the corpus Knowledge Base couldn't be searched")
def search(query: str, *, doc_type: str | None = None, section_path: str | None = None, gated: bool = True) -> list[Document]:
    """ hits, best first by similarity; below-threshold hits dropped unless gated is False (threshold tuning) """

    # the question is embedded while the KB searches, so scoring adds little beyond the KB's own latency
    with ThreadPoolExecutor(max_workers=1) as pool:
        question = pool.submit(clients.embeddings().embed_query, query)
        found = build_retriever(doc_type, section_path).invoke(query)
        hits = rescore(question.result(), found)
    if not gated:
        return hits
    return [hit for hit in hits if hit.metadata["score"] >= settings.retrieval_score_threshold]
