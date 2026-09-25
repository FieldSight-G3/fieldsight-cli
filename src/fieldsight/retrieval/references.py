""" search filters from a question, and second hops from chunk cross-references """

import calendar
import re
from datetime import datetime
from functools import cache

from langchain_core.documents import Document

from ..ingest.corpus.sources import letters
from ..schemas.retrieval import Hop
from ..types.corpus import DocType
from .corpus import meta

# cap on second hops per question
MAX_HOPS = 3

# a Part 1904 section, e.g. "1904.39", "1904.7(b)(5)(ii)", "29 CFR 1904.29"
PART_1904 = re.compile(r"\b1904\.\d+\b")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
WRITTEN_DATE = re.compile(rf"\b(?:{'|'.join(calendar.month_name[1:])}) \d{{1,2}}, \d{{4}}\b")

# cues that point a question at one corpus layer
DOC_TYPE_CUES: list[tuple[re.Pattern, DocType]] = [
    (re.compile(r"letters? of interpretation|interpretation letter|\bLOI\b", re.IGNORECASE), "interpretation"),
    (re.compile(r"preamble|federal register|rulemaking|\b79 FR\b", re.IGNORECASE), "preamble"),
    (re.compile(r"directive|\bCPL\b|compliance officer", re.IGNORECASE), "directive"),
]

known_letters = cache(letters)


def cited_letters(text: str) -> list[str]:
    """ dates of corpus letters the text cites, ISO or written out """

    written = [datetime.strptime(date, "%B %d, %Y").date().isoformat() for date in WRITTEN_DATE.findall(text)]  # noqa: DTZ007 - date only
    return [date for date in dict.fromkeys(ISO_DATE.findall(text) + written) if date in known_letters()]


def pick_filter(question: str) -> tuple[DocType | None, str | None, str]:
    """ first search's doc_type, section_path and reason; narrowed only if the question names a layer, letter or single section """

    for cue, doc_type in DOC_TYPE_CUES:
        if cue.search(question):
            return doc_type, None, f"the question points at the {doc_type} layer"
    if cited_letters(question):
        return "interpretation", None, "the question names a letter of interpretation"
    sections = set(PART_1904.findall(question))
    if len(sections) == 1:
        section = sections.pop()
        return "regulation", section, f"the question names section {section}"
    return None, None, "the question"


def section_hops(question: str, docs: list[Document]) -> list[Hop]:
    """ Part 1904 sections cited by non-regulation chunks but not yet retrieved, in citation order """

    reached = {meta(doc)["section_path"] for doc in docs if meta(doc)["doc_type"] == "regulation"}
    hops: dict[str, Hop] = {}
    for doc in docs:
        if meta(doc)["doc_type"] == "regulation":
            continue
        for section in PART_1904.findall(doc.page_content):
            if section not in reached:
                hops.setdefault(section, Hop(query=question, doc_type="regulation", section_path=section,
                                             reason=f"{meta(doc)['chunk_id']} cites section {section}"))
    return list(hops.values())


def letter_hops(docs: list[Document]) -> list[Hop]:
    """ letters cited by directive or preamble chunks but not yet retrieved, searched by title """

    reached = {meta(doc)["section_path"] for doc in docs if meta(doc)["doc_type"] == "interpretation"}
    hops: dict[str, Hop] = {}
    for doc in docs:
        if meta(doc)["doc_type"] not in ("directive", "preamble"):
            continue
        for date in cited_letters(doc.page_content):
            if date not in reached:
                hops.setdefault(date, Hop(query=known_letters()[date], doc_type="interpretation",
                                          reason=f"{meta(doc)['chunk_id']} cites the {date} letter"))
    return list(hops.values())


def hop_targets(question: str, docs: list[Document]) -> list[Hop]:
    """ second hops for a first search's chunks, sections first, capped at MAX_HOPS """

    return (section_hops(question, docs) + letter_hops(docs))[:MAX_HOPS]
