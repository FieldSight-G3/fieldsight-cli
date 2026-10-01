"""Corpus chunking keeps tables Textract's TABLES feature missed, and files a single-section doc's tables under it."""

from fieldsight.ingest.corpus.layout import tables_by_page
from fieldsight.ingest.corpus.sections import section_path


def block(block_id: str, kind: str, children: list[str] = (), text: str = "", page: int = 1) -> dict:
    found = {"Id": block_id, "BlockType": kind, "Page": page}
    if children:
        found["Relationships"] = [{"Type": "CHILD", "Ids": list(children)}]
    if text:
        found["Text"] = text
    return found


def line(block_id: str, text: str) -> list[dict]:
    """ a LINE with one WORD per token """

    words = [block(f"{block_id}-w{n}", "WORD", text=token) for n, token in enumerate(text.split())]
    return [block(block_id, "LINE", [w["Id"] for w in words], text=text), *words]


TITLE = [block("title", "LAYOUT_SECTION_HEADER", ["title-line"]), *line("title-line", "Table R-6 Minimum Approach Distances")]
ROWS = [*line("row-1", "5.1 to 15.0 0.65 2.14 0.68 2.24"), *line("row-2", "15.1 to 36.0 0.77 2.53 0.89 2.92")]


def test_a_layout_table_no_structured_table_covers_is_kept_under_its_heading():
    blocks = TITLE + [block("layout-table", "LAYOUT_TABLE", ["row-1", "row-2"])] + ROWS

    [table] = tables_by_page(blocks)[1]
    assert table.splitlines() == ["## Table R-6 Minimum Approach Distances", "5.1 to 15.0 0.65 2.14 0.68 2.24",
                                  "15.1 to 36.0 0.77 2.53 0.89 2.92"]


def test_a_layout_table_a_structured_table_covers_is_not_rendered_twice():
    words = [b["Id"] for b in ROWS if b["BlockType"] == "WORD"]
    cell = block("cell", "CELL", words)
    cell |= {"RowIndex": 1, "ColumnIndex": 1}
    blocks = TITLE + [block("table", "TABLE", ["cell"]), cell, block("layout-table", "LAYOUT_TABLE", ["row-1", "row-2"])] + ROWS

    assert len(tables_by_page(blocks)[1]) == 1


def test_a_single_section_docs_untitled_header_belongs_to_that_section():
    regulation = {"doc_id": "CFR-269", "title": "29 CFR 1910.269 - Electric Power Generation"}
    part = {"doc_id": "CFR-1904", "title": "29 CFR Part 1904 - Recording and Reporting"}

    assert section_path(regulation, 6, "Table R-6 Minimum Approach Distances") == "1910.269"
    assert section_path(part, 3, "What is first aid?") == "What is first aid?"
    assert section_path(part, 3, "1904.7 General recording criteria") == "1904.7"
