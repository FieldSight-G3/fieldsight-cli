""" labelled form fields from a packet artifact's Textract blocks """

from ...types.artifacts import EXTRACTED_FIELD, ExtractedField
from ..blocks import index_blocks, related, text_of


def key_values(blocks: list[dict], by_id: dict[str, dict]) -> list[tuple[dict, dict]]:
    """ every (key block, value block) pair from a FORMS analysis """

    pairs = []
    for block in blocks:
        if block.get("BlockType") != "KEY_VALUE_SET" or "KEY" not in block.get("EntityTypes", []):
            continue
        values = related(block, by_id, "VALUE")
        if values:
            pairs.append((block, values[0]))
    return pairs


def extract_form_fields(blocks: list[dict], artifact: str) -> list[ExtractedField]:
    """ every filled-in form field, traced to its artifact and page """

    by_id = index_blocks(blocks)

    fields = []
    for key, value in key_values(blocks, by_id):
        label = text_of(key, by_id).strip().rstrip(":").lower()
        if not label:
            continue

        # a misread label is as bad as a misread value, so take the weaker of the two
        confidence = min(key.get("Confidence", 0.0), value.get("Confidence", 0.0)) / 100

        fields.append(EXTRACTED_FIELD.validate_python({
            "label": label, "value": text_of(value, by_id), "confidence": confidence, "artifact": artifact, "page": value.get("Page", 1),
        }))

    return fields
