""" section designations for corpus chunks, from headers or excerpt page ranges """

import re

from ...types.corpus import CorpusDoc

# a CFR section (1904.39, 1910.269) or a letter-of-interpretation date (2021-01-08)
DESIGNATION = re.compile(r"\d{4}\.\d+|\d{4}-\d{2}-\d{2}")


def section_label(header: str) -> str:
    """ the designation a header names, or the header itself when it names none """

    match = DESIGNATION.search(header)
    return match.group() if match else header


def excerpt_path(doc: CorpusDoc, page: int) -> str | None:
    """ section_path of the excerpt covering a page, for docs cut from page ranges """

    start = 1
    for excerpt in doc.get("excerpts", []):
        end = start + excerpt["pdf_pages"][1] - excerpt["pdf_pages"][0]
        if start <= page <= end:
            return excerpt["section_path"]
        start = end + 1
    return None


def section_path(doc: CorpusDoc, page: int, header: str | None) -> str:
    """ the excerpt's path for page-range docs (finer designations aren't printed), else the header's designation """

    return excerpt_path(doc, page) or (section_label(header) if header else doc["doc_id"])
