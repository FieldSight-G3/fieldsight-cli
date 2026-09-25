""" split a cracked corpus doc into chunks: headed sections capped by size, plus whole tables """

import hashlib

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from ...types.corpus import CHUNK_METADATA, CorpusDoc
from .layout import header_in_force, layout_by_page, page_markdown, tables_by_page
from .sections import section_path

# ~300 / ~50 words: small enough that one chunk is about one regulatory provision
CHUNK_CHARS = 1800
OVERLAP_CHARS = 300

HEADINGS = MarkdownHeaderTextSplitter([("##", "header")], strip_headers=False)
SIZE = RecursiveCharacterTextSplitter(chunk_size=CHUNK_CHARS, chunk_overlap=OVERLAP_CHARS)


def chunk_metadata(doc: CorpusDoc, page: int, header: str | None) -> dict:
    """ what the KB filters and cites on; chunk_id is added once the chunks are final """

    return {"doc_id": doc["doc_id"], "title": doc["title"], "doc_type": doc["doc_type"],
            "section_path": section_path(doc, page, header), "page": page}


def split_pages(doc: CorpusDoc, layout: dict[int, list[tuple[str, str]]]) -> list[Document]:
    """ each page split on its headers; a page that opens mid-section carries the header from the page before """

    in_force, carried, chunks = header_in_force(layout), None, []
    for page, items in sorted(layout.items()):
        markdown = (f"## {carried}\n\n" if carried else "") + page_markdown(items)
        for chunk in HEADINGS.split_text(markdown):
            chunks.append(Document(page_content=chunk.page_content, metadata=chunk_metadata(doc, page, chunk.metadata.get("header"))))
        carried = in_force[page]
    return chunks


def split_tables(doc: CorpusDoc, blocks: list[dict], in_force: dict[int, str | None]) -> list[Document]:
    """ one whole chunk per table, never size-split, so its rows and columns stay together """

    return [
        Document(page_content=table, metadata=chunk_metadata(doc, page, in_force.get(page)))
        for page, tables in sorted(tables_by_page(blocks).items())
        for table in tables
    ]


def has_body(chunk: Document) -> bool:
    """ False for a chunk that is only a heading, e.g. a table caption whose table is chunked on its own """

    return any(not line.startswith("## ") for line in chunk.page_content.splitlines() if line.strip())


def chunk_id(chunk: Document) -> str:
    """ stable across runs: the same text in the same section and page always gets the same id """

    meta = chunk.metadata
    digest = hashlib.sha256(f"{meta['section_path']}|{meta['page']}|{chunk.page_content}".encode()).hexdigest()[:12]
    return f"{meta['doc_id']}-{digest}"


def with_chunk_id(chunk: Document) -> Document:
    """ the chunk with its id added, its metadata checked against the ChunkMetadata type """

    metadata = CHUNK_METADATA.validate_python({**chunk.metadata, "chunk_id": chunk_id(chunk)})
    return Document(page_content=chunk.page_content, metadata=metadata)


def split_corpus_doc(doc: CorpusDoc, blocks: list[dict]) -> list[Document]:
    """ a cracked corpus doc as chunks: headed sections capped at CHUNK_CHARS, plus whole tables """

    layout = layout_by_page(blocks)
    sections = [chunk for chunk in SIZE.split_documents(split_pages(doc, layout)) if has_body(chunk)]
    return [with_chunk_id(chunk) for chunk in sections + split_tables(doc, blocks, header_in_force(layout))]
