""" read a corpus doc's Textract LAYOUT and TABLES blocks: headers, text and tables per page """

from ..blocks import index_blocks, related, text_of

# Textract layout blocks the corpus keeps; lists, figures, page headers/footers and page numbers are skipped
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
        if text:
            pages.setdefault(block.get("Page", 1), []).append((kind, text))
    return pages


def render_table(table: dict, by_id: dict[str, dict]) -> str:
    """ a TABLE block as |-joined rows, so its columns survive into the chunk """

    rows: dict[int, dict[int, str]] = {}
    for cell in related(table, by_id, "CHILD"):
        if cell.get("BlockType") == "CELL":
            rows.setdefault(cell["RowIndex"], {})[cell["ColumnIndex"]] = text_of(cell, by_id)
    return "\n".join(" | ".join(row[col] for col in sorted(row)) for _, row in sorted(rows.items()))


def tables_by_page(blocks: list[dict]) -> dict[int, list[str]]:
    """ each page's tables, rendered """

    by_id = index_blocks(blocks)
    pages: dict[int, list[str]] = {}
    for block in blocks:
        if block.get("BlockType") == "TABLE":
            pages.setdefault(block.get("Page", 1), []).append(render_table(block, by_id))
    return pages


def page_markdown(items: list[tuple[str, str]]) -> str:
    """ one page's layout as Markdown: headers become ## lines, text becomes paragraphs """

    return "\n\n".join(f"## {text}" if kind == "header" else text for kind, text in items)


def header_in_force(layout: dict[int, list[tuple[str, str]]]) -> dict[int, str | None]:
    """ the last header seen on or before each page """

    header, in_force = None, {}
    for page, items in sorted(layout.items()):
        header = next((text for kind, text in reversed(items) if kind == "header"), header)
        in_force[page] = header
    return in_force
