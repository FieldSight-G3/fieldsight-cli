""" search the regulatory corpus and turn the hits into citable sources """

from langchain_core.documents import Document

from ..aws import clients
from ..aws.errors import raises
from ..errors import RetrievalError
from ..types.corpus import SOURCE, Source


def kb_filter(doc_type: str | None, section_path: str | None) -> dict | None:
    """ the KB's filter syntax for whichever of doc_type and section_path are given """

    conditions = [{"equals": {"key": key, "value": value}} for key, value in (("doc_type", doc_type), ("section_path", section_path)) if value]
    if len(conditions) > 1:
        return {"andAll": conditions}
    return conditions[0] if conditions else None


def to_chunk(hit: Document) -> Document:
    """ a KB hit with its metadata checked against Source and flattened to our chunk fields plus its score """

    attributes = {
        key: value for key, value in hit.metadata["source_metadata"].items() if key in Source.__annotations__}
    
    return Document(
        page_content=hit.page_content, 
        metadata=SOURCE.validate_python({**attributes, "score": hit.metadata["score"]})
        )


@raises(RetrievalError, "the corpus Knowledge Base couldn't be searched")
def search(
    query: str,
    *, 
    doc_type: str | None = None, 
    section_path: str | None = None
    ) -> list[Document]:
    """ corpus chunks above the score threshold, best first, optionally narrowed, carrying our chunk metadata and score """

    retriever = clients.corpus_retriever(kb_filter(doc_type, section_path))
    return [to_chunk(hit) for hit in retriever.invoke(query)]


def to_sources(chunks: list[Document]) -> list[Source]:
    """ the sources array for a set of retrieved chunks """

    return [SOURCE.validate_python(chunk.metadata) for chunk in chunks]
