""" the corpus KB as a retriever: top-k hits above the score threshold, optionally filtered by metadata """

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from ..aws import clients
from ..aws.errors import raises
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


def build_retriever(doc_type: str | None = None, section_path: str | None = None, gated: bool = True) -> BaseRetriever:
    """ corpus KB retriever, optionally filtered; ungated only for threshold tuning """

    return clients.corpus_retriever(kb_filter(doc_type, section_path), gated=gated)


@raises(RetrievalError, "the corpus Knowledge Base couldn't be searched")
def search(query: str, *, doc_type: str | None = None, section_path: str | None = None, gated: bool = True) -> list[Document]:
    """ hits, best first; below-threshold hits dropped unless gated is False """

    return build_retriever(doc_type, section_path, gated).invoke(query)
