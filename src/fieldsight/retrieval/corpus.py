""" the corpus KB as a retriever: top-k hits above the score threshold, optionally filtered by metadata

    The corpus KB is a Bedrock-managed KB, whose scores are relative to each query (its best hit scores near 1.0
    even for a question the corpus can't answer), so they can't gate a refusal. Each hit is rescored here as the
    cosine similarity of its Titan v2 embedding to the query's, the same model the KB indexes with, and the
    threshold gates on that.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from ..aws import clients
from ..aws.errors import raises
from ..config import settings
from ..errors import RetrievalError
from ..ingest.corpus.outline import covers


def kb_filter(doc_type: str | None, section_path: str | None, paragraph: str | None = None) -> dict | None:
    """ KB filter for whichever of doc_type, section_path and paragraph are given """

    conditions = [{"equals": {"key": key, "value": value}}
                  for key, value in (("doc_type", doc_type), ("section_path", section_path), ("paragraph", paragraph)) if value]
    if len(conditions) > 1:
        return {"andAll": conditions}
    return conditions[0] if conditions else None


def meta(hit: Document) -> dict:
    """ our chunk metadata on a KB hit """

    return hit.metadata["source_metadata"]


def build_retriever(doc_type: str | None = None, section_path: str | None = None, paragraph: str | None = None) -> BaseRetriever:
    """ corpus KB retriever, optionally filtered; ungated, because search gates on its own score """

    return clients.corpus_retriever(kb_filter(doc_type, section_path, paragraph))


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


# a CFR provision as rule sources name it: "29 CFR 1904.7(b)(5)(ii)" -> section 1904.7, path 1904.7(b)(5)(ii)
PROVISION = re.compile(r"(\d{4}\.\d+)((?:\([^)]+\))*)")


@raises(RetrievalError, "the corpus Knowledge Base couldn't be searched")
def provision_text(provision: str) -> list[Document]:
    """ the regulation chunks that state a provision: its own paragraph's, or, when its text sits in a parent chunk
        with its siblings (a short list is chunked whole), that parent's; for a bare section, its paragraphs """

    found = PROVISION.search(provision)
    if not found:
        return []
    section, path = found.group(1), found.group(1) + found.group(2)
    candidate = path
    while True:
        hits = build_retriever("regulation", section, candidate).invoke(path)
        hits = [hit for hit in hits if covers(meta(hit).get("paragraph", ""), hit.page_content, path)]
        if hits or candidate == section:
            break
        candidate = candidate[:candidate.rindex("(")]
    if not hits and candidate == section:
        hits = [hit for hit in build_retriever("regulation", section).invoke(path)
                if covers(meta(hit).get("paragraph", ""), hit.page_content, path)]
    return rescore(clients.embeddings().embed_query(provision), hits)
