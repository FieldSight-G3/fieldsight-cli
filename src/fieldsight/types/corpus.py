""" shapes of corpus data in the ingestion and retrieval pipeline: plain dicts, validated at the boundary """

from typing import Literal, NotRequired, TypedDict

from pydantic import ConfigDict, TypeAdapter, with_config

DocType = Literal["regulation", "directive", "preamble", "interpretation", "form"]


class Excerpt(TypedDict):
    """ one page range cut from an upstream PDF """

    section_path: str
    label: str
    pdf_pages: tuple[int, int]


class CorpusDoc(TypedDict):
    """ one corpus document from sources.json; the fetch settings it also carries are dropped on validation """

    doc_id: str
    title: str
    doc_type: DocType
    kind: str
    excerpts: NotRequired[list[Excerpt]]


@with_config(ConfigDict(extra="forbid"))
class ChunkMetadata(TypedDict):
    """ what every chunk carries into the KB, so it can be filtered and cited """

    doc_id: str
    title: str
    doc_type: DocType
    section_path: str
    paragraph: str      # the paragraph the chunk states, e.g. 1904.7(b)(5)(ii); the section for unoutlined docs
    page: int
    chunk_id: str


CORPUS_DOC = TypeAdapter(CorpusDoc)
CHUNK_METADATA = TypeAdapter(ChunkMetadata)
