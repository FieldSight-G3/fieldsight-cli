""" per-page headers, text and tables from a corpus doc's Textract LAYOUT and TABLES blocks """

import re

from ..blocks import index_blocks, related, text_of

# a letter of interpretation's title line: its date, then its subject, e.g. "2021-01-08 - Reporting two related ..."
LETTER_TITLE = re.compile(r"\d{4}-\d{2}-\d{2} - ")

# layout blocks kept; lists, figures, page headers/footers and page numbers are skipped
LAYOUT_KINDS = {
    "LAYOUT_TITLE": "header", 
    "LAYOUT_SECTION_HEADER": "header", 
    "LAYOUT_TEXT": "text"
    }


def layout_by_page(blocks: list[dict]) -> dict[int, list[tuple[str, str]]]:
    """ each page's headers and text in reading order, as (kind, text) """

    by_id = index_blocks(blocks)
    pages: dict[int, list[tuple[str, str]]] = {}
    for block in blocks:
        kind = LAYOUT_KINDS.get(block.get("BlockType", ""))
        if not kind:
            continue
        text = " ".join(line.get("Text", "") for line in related(block, by_id, "CHILD"))
        if kind == "text" and LETTER_TITLE.match(text):
            # a letter of interpretation opens with its date, printed as text: it heads the letter's section
            kind = "header"
        if text:
            pages.setdefault(block.get("Page", 1), []).append((kind, text))
    return pages


def render_table(table: dict, by_id: dict[str, dict]) -> str:
    """ a TABLE block as |-joined rows, keeping its columns """

    rows: dict[int, dict[int, str]] = {}
    for cell in related(table, by_id, "CHILD"):
        if cell.get("BlockType") == "CELL":
            rows.setdefault(cell["RowIndex"], {})[cell["ColumnIndex"]] = text_of(cell, by_id)
    return "\n".join(" | ".join(row[col] for col in sorted(row)) for _, row in sorted(rows.items()))


def words_under(block: dict, by_id: dict[str, dict]) -> set[str]:
    """ the WORD ids beneath a block, through its lines or cells """

    found: set[str] = set()
    for child in related(block, by_id, "CHILD"):
        if child.get("BlockType") == "WORD":
            found.add(child["Id"])
        else:
            found |= words_under(child, by_id)
    return found


def tables_by_page(blocks: list[dict]) -> dict[int, list[str]]:
    """ each page's tables, rendered

        Textract's TABLES feature can miss a table its LAYOUT feature found, typically one with a merged, multi-row
        header. Such a layout table is rendered from its own lines, under the heading just before it, so its rows
        are indexed instead of dropped.
    """

    by_id = index_blocks(blocks)
    pages: dict[int, list[str]] = {}
    covered: set[str] = set()
    for block in blocks:
        if block.get("BlockType") == "TABLE":
            pages.setdefault(block.get("Page", 1), []).append(render_table(block, by_id))
            covered |= words_under(block, by_id)

    heading: dict[int, str] = {}
    for block in blocks:
        page = block.get("Page", 1)
        if block.get("BlockType") in ("LAYOUT_SECTION_HEADER", "LAYOUT_TITLE", "LAYOUT_TEXT"):
            heading[page] = " ".join(line.get("Text", "") for line in related(block, by_id, "CHILD"))
        elif block.get("BlockType") == "LAYOUT_TABLE":
            words = words_under(block, by_id)
            if words and len(words & covered) < len(words) / 2:
                rows = "\n".join(line.get("Text", "") for line in related(block, by_id, "CHILD") if line.get("Text"))
                title = heading.get(page, "")
                pages.setdefault(page, []).append(f"## {title}\n{rows}" if title else rows)
    return pages


def page_markdown(items: list[tuple[str, str]]) -> str:
    """ a page as Markdown: headers as ## lines, text as paragraphs """

    return "\n\n".join(f"## {text}" if kind == "header" else text for kind, text in items)


def header_in_force(layout: dict[int, list[tuple[str, str]]]) -> dict[int, str | None]:
    """ the last header seen on or before each page """

    header, in_force = None, {}
    for page, items in sorted(layout.items()):
        header = next((text for kind, text in reversed(items) if kind == "header"), header)
        in_force[page] = header
    return in_force
