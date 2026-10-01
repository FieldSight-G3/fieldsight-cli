""" split a cracked corpus doc into chunks: headed sections capped by size, plus whole tables """

import hashlib

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from ...types.corpus import CHUNK_METADATA, CorpusDoc
from . import outline
from .layout import header_in_force, layout_by_page, page_markdown, tables_by_page
from .sections import section_path

# ~300 / ~50 words, so a chunk covers about one provision
CHUNK_CHARS = 1800
OVERLAP_CHARS = 300

HEADINGS = MarkdownHeaderTextSplitter([("##", "header")], strip_headers=False)
SIZE = RecursiveCharacterTextSplitter(chunk_size=CHUNK_CHARS, chunk_overlap=OVERLAP_CHARS)


def chunk_metadata(doc: CorpusDoc, page: int, header: str | None, paragraph: str | None = None,
                   section: str | None = None) -> dict:
    """ metadata the KB filters and cites on; chunk_id is added later """

    section = section or section_path(doc, page, header)
    return {
        "doc_id": doc["doc_id"],
        "title": doc["title"],
        "doc_type": doc["doc_type"],
        "section_path": section,
        "paragraph": paragraph or section,
        "page": page
        }


def split_paragraphs(doc: CorpusDoc, layout: dict[int, list[tuple[str, str]]]) -> list[Document]:
    """ a CFR regulation as one chunk per paragraph (outline.py), each carrying its paragraph path; [] when the doc
        isn't laid out by CFR section headers """

    items = [(page, kind, text) for page, page_items in sorted(layout.items()) for kind, text in page_items]
    found = outline.paragraphs(items)
    if not found:
        return []
    documents = []
    for paragraph, text in outline.chunks(found):
        if not paragraph.markers and len(text.splitlines()) <= 2:
            continue  # a bare section header; its paragraphs carry it
        parts = SIZE.split_text(text) if len(text) > outline.CHUNK_CHARS else [text]
        first_line = text.splitlines()[0]
        for number, part in enumerate(parts):
            content = part if number == 0 else f"{first_line}\n{part}"
            documents.append(Document(page_content=content, metadata=chunk_metadata(
                doc, paragraph.page, None, paragraph=paragraph.path, section=paragraph.section)))
    return documents


def split_pages(doc: CorpusDoc, layout: dict[int, list[tuple[str, str]]]) -> list[Document]:
    """ split each page on headers; a page opening mid-section inherits the previous header """

    in_force, carried, chunks = header_in_force(layout), None, []
    for page, items in sorted(layout.items()):
        markdown = (f"## {carried}\n\n" if carried else "") + page_markdown(items)
        for chunk in HEADINGS.split_text(markdown):
            chunks.append(Document(page_content=chunk.page_content, metadata=chunk_metadata(doc, page, chunk.metadata.get("header"))))
        carried = in_force[page]
    return chunks


def table_parts(table: str) -> list[str]:
    """ a table as chunks no bigger than CHUNK_CHARS: whole when it fits; otherwise its rows in groups, each opening
        with the table's title and header row, so every piece reads as the table it came from. A "table" with no
        rows is prose Textract took for one (a multi-column page), and is split like prose. """

    if len(table) <= CHUNK_CHARS:
        return [table]
    lines = table.splitlines()
    if len(lines) < 3:
        return SIZE.split_text(table)
    head = lines[:2] if lines[0].startswith("## ") else lines[:1]
    parts, current = [], list(head)
    for line in lines[len(head):]:
        if len("\n".join(current + [line])) > CHUNK_CHARS and len(current) > len(head):
            parts.append("\n".join(current))
            current = list(head)
        current.append(line)
    parts.append("\n".join(current))
    # a single row longer than a chunk is split like prose
    return [piece for part in parts for piece in (SIZE.split_text(part) if len(part) > CHUNK_CHARS else [part])]


def split_tables(doc: CorpusDoc, blocks: list[dict], in_force: dict[int, str | None]) -> list[Document]:
    """ each table as one chunk, or in row groups under its header when it's bigger than a chunk """

    return [
        Document(page_content=part, metadata=chunk_metadata(doc, page, in_force.get(page)))
        for page, tables in sorted(tables_by_page(blocks).items())
        for table in tables
        for part in table_parts(table)
    ]


def has_body(chunk: Document) -> bool:
    """ False for a heading-only chunk, e.g. a caption whose table is chunked separately """

    return any(not line.startswith("## ") for line in chunk.page_content.splitlines() if line.strip())


def chunk_id(chunk: Document) -> str:
    """ stable id: the same text, section and page always give the same id """

    meta = chunk.metadata
    digest = hashlib.sha256(f"{meta['section_path']}|{meta['page']}|{chunk.page_content}".encode()).hexdigest()[:12]
    return f"{meta['doc_id']}-{digest}"


def with_chunk_id(chunk: Document) -> Document:
    """ the chunk with its id, metadata validated as ChunkMetadata """

    metadata = CHUNK_METADATA.validate_python({**chunk.metadata, "chunk_id": chunk_id(chunk)})
    return Document(page_content=chunk.page_content, metadata=metadata)


def split_corpus_doc(doc: CorpusDoc, blocks: list[dict]) -> list[Document]:
    """ a cracked corpus doc as chunks: headed sections capped at CHUNK_CHARS, plus whole tables """

    layout = layout_by_page(blocks)
    outlined = split_paragraphs(doc, layout) if doc["doc_type"] == "regulation" else []
    sections = outlined or [chunk for chunk in SIZE.split_documents(split_pages(doc, layout)) if has_body(chunk)]
    return [with_chunk_id(chunk) for chunk in sections + split_tables(doc, blocks, header_in_force(layout))]
