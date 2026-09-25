""" Textract block helpers shared by packet and corpus extraction """


def index_blocks(blocks: list[dict]) -> dict[str, dict]:
    """ blocks keyed by id, so relationships can be followed """

    return {block["Id"]: block for block in blocks if block.get("Id")}


def related(block: dict, by_id: dict[str, dict], relation: str) -> list[dict]:
    """ blocks linked by a relationship type, e.g. CHILD or VALUE """

    return [
        by_id[block_id]
        for relationship in block.get("Relationships", [])
        if relationship.get("Type") == relation
        for block_id in relationship.get("Ids", [])
        if block_id in by_id
    ]


def text_of(block: dict, by_id: dict[str, dict]) -> str:
    """ a block's child words joined, with a ticked checkbox as "true" """

    words = []
    for child in related(block, by_id, "CHILD"):
        if child.get("BlockType") == "WORD":
            words.append(child.get("Text", ""))
        elif child.get("SelectionStatus") == "SELECTED":
            words.append("true")
    return " ".join(words)
