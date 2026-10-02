""" how a cracked text splits into paragraphs: the unit the Prompt Attacks screen withholds """

import re


def paragraphs(text: str) -> list[str]:
    """ a cracked text's paragraphs: blank-line blocks, or its lines when it has no blank lines """

    blocks = [block for block in re.split(r"\n\s*\n", text) if block.strip()]
    return blocks if len(blocks) > 1 else [line for line in text.splitlines() if line.strip()] or [text]
