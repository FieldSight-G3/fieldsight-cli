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
    page: int
    chunk_id: str


class Source(ChunkMetadata):
    """ one entry of a grounded answer's sources array: a chunk and how well it matched """

    score: float


CORPUS_DOC = TypeAdapter(CorpusDoc)
CHUNK_METADATA = TypeAdapter(ChunkMetadata)
SOURCE = TypeAdapter(Source)
