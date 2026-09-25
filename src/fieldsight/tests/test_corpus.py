""" corpus chunking against the requirements for corpus ingestion, on hand-built Textract blocks """

from fieldsight.ingest.corpus.chunking import CHUNK_CHARS, split_corpus_doc
from fieldsight.types.corpus import CorpusDoc

DOC = CorpusDoc(doc_id="CFR-1904", title="29 CFR Part 1904", doc_type="regulation", kind="ecfr")


def layout(kind: str, text: str, n: int) -> list[dict]:
    """ one LAYOUT block on page 1 and the LINE under it """

    return [
        {"Id": f"b{n}", "BlockType": kind, "Page": 1, "Relationships": [{"Type": "CHILD", "Ids": [f"l{n}"]}]},
        {"Id": f"l{n}", "BlockType": "LINE", "Text": text, "Page": 1},
    ]


def table() -> list[dict]:
    """ a 2x2 TABLE on page 1 with its CELLs and WORDs """

    cells = [(1, 1, "Voltage"), (1, 2, "Distance"), (2, 1, "72.6"), (2, 2, "1.02")]
    blocks = [{"Id": "t", "BlockType": "TABLE", "Page": 1, "Relationships": [{"Type": "CHILD", "Ids": ["c0", "c1", "c2", "c3"]}]}]
    for i, (row, col, text) in enumerate(cells):
        blocks.append({"Id": f"c{i}", "BlockType": "CELL", "RowIndex": row, "ColumnIndex": col, "Page": 1,
                       "Relationships": [{"Type": "CHILD", "Ids": [f"w{i}"]}]})
        blocks.append({"Id": f"w{i}", "BlockType": "WORD", "Text": text, "Page": 1})
    return blocks


def test_chunks_split_on_headings():
    blocks = layout("LAYOUT_SECTION_HEADER", "1904.4 Recording criteria", 1) + layout("LAYOUT_TEXT", "Record it.", 2) \
        + layout("LAYOUT_SECTION_HEADER", "1904.39 Reporting", 3) + layout("LAYOUT_TEXT", "Within eight hours.", 4)
    assert [c.metadata["section_path"] for c in split_corpus_doc(DOC, blocks)] == ["1904.4", "1904.39"]


def test_long_sections_fall_back_to_size():
    chunks = split_corpus_doc(DOC, layout("LAYOUT_TEXT", "word " * 1500, 1))
    assert len(chunks) > 1
    assert all(len(c.page_content) <= CHUNK_CHARS for c in chunks)


def test_table_columns_survive():
    assert [c.page_content for c in split_corpus_doc(DOC, table())] == ["Voltage | Distance\n72.6 | 1.02"]


def test_every_chunk_carries_the_filterable_metadata():
    chunk = split_corpus_doc(DOC, layout("LAYOUT_TEXT", "Record it.", 1))[0]
    assert set(chunk.metadata) == {"doc_id", "title", "doc_type", "section_path", "page", "chunk_id"}


def test_chunk_ids_are_stable():
    blocks = layout("LAYOUT_TEXT", "Record it.", 1)
    assert split_corpus_doc(DOC, blocks)[0].metadata["chunk_id"] == split_corpus_doc(DOC, blocks)[0].metadata["chunk_id"]
