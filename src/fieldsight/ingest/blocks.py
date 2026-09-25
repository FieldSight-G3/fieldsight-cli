""" helpers for walking Textract blocks, shared by packet field extraction and corpus chunking """


def index_blocks(blocks: list[dict]) -> dict[str, dict]:
    """ blocks keyed by id, so relationships can be followed """

    return {block["Id"]: block for block in blocks if block.get("Id")}


def related(block: dict, by_id: dict[str, dict], relation: str) -> list[dict]:
    """ every block linked to this one by the given relationship type, e.g. CHILD or VALUE """

    return [
        by_id[block_id]
        for relationship in block.get("Relationships", [])
        if relationship.get("Type") == relation
        for block_id in relationship.get("Ids", [])
        if block_id in by_id
    ]


def text_of(block: dict, by_id: dict[str, dict]) -> str:
    """ the words under a block joined up, with a ticked checkbox read as "true" """

    words = []
    for child in related(block, by_id, "CHILD"):
        if child.get("BlockType") == "WORD":
            words.append(child.get("Text", ""))
        elif child.get("SelectionStatus") == "SELECTED":
            words.append("true")
    return " ".join(words)
