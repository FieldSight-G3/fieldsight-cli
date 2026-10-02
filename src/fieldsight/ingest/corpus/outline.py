""" a regulation section as its paragraphs, by the outline markers it prints: (a), (1), (i), (A)

    A claim is grounded by one paragraph, e.g. 1904.7(b)(5)(ii), not by "somewhere in 1904.7". Each layout text block
    of a CFR section opens with its paragraph's marker, so the outline can be followed block by block: a block with no
    marker continues the paragraph before it (a paragraph broken across a page), and a heading can open two levels at
    once ("(b) Implementation-(1) How do I ..."). Each chunk then carries its paragraph path, and a short list is kept
    whole with its stem, so the paragraph that defines first aid is one chunk holding its whole list.
"""

import re
from dataclasses import dataclass, field

# a CFR section header as the layout reads it: "§ 1904.7 General recording criteria."
# (the "§" can arrive as U+FFFD from Textract; a header without it, like 1910.269's "paragraph (l)" headers, isn't one)
SECTION_HEADER = re.compile(r"^[\u00a7\ufffd]\s*(\d{4}\.\d+)\s+\S")
MARKER = re.compile(r"^\(([a-z]{1,4}|\d{1,2}|[A-Z])\)")
# a heading between two markers: "(b) Implementation-(1) How do I ..."
CHAINED = re.compile(r"^\(([a-z]{1,4}|\d{1,2})\)\s*[^()]{0,80}?[-–—]\s*\(([a-z]{1,4}|\d{1,2}|[A-Z])\)")
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10, "xi": 11,
         "xii": 12, "xiii": 13, "xiv": 14, "xv": 15, "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20}

# a child list this short is kept whole with its stem, so a definition and its list stay one chunk
SHORT_CHILD_CHARS = 450
CHUNK_CHARS = 2600


@dataclass
class Paragraph:
    section: str
    markers: list[str]
    page: int
    text: str

    @property
    def path(self) -> str:
        return self.section + "".join(f"({marker})" for marker in self.markers)


@dataclass
class Outline:
    section: str | None = None
    markers: list[str] = field(default_factory=list)  # the open marker at each level, 1 to 4

    def level(self, marker: str) -> int:
        """ 1 lowercase letter, 2 number, 3 roman numeral, 4 capital letter; a lowercase roman is a letter only when
            it's the next letter at level 1 and no deeper level is open """

        if marker.isdigit():
            return 2
        if marker.isupper():
            return 4
        if marker in ROMAN and len(self.markers) >= 2:
            open_roman = self.markers[2] if len(self.markers) >= 3 else None
            if marker == "i" or (open_roman in ROMAN and ROMAN[marker] == ROMAN[open_roman] + 1):
                return 3
        expected = chr(ord(self.markers[0]) + 1) if self.markers else "a"
        if marker == expected or marker not in ROMAN:
            return 1
        return 3

    def open(self, marker: str) -> None:
        level = self.level(marker)
        self.markers = self.markers[:level - 1] + [marker]


def leading_markers(text: str) -> list[str]:
    """ the markers a block opens with: one, or two when a heading sits between them """

    chained = CHAINED.match(text)
    if chained:
        return [chained.group(1), chained.group(2)]
    single = MARKER.match(text)
    return [single.group(1)] if single else []


def paragraphs(items: list[tuple[int, str, str]]) -> list[Paragraph]:
    """ (page, kind, text) layout items, in reading order, as the paragraphs of each CFR section they hold """

    outline, found = Outline(), []
    for page, kind, text in items:
        header = SECTION_HEADER.match(text) if kind == "header" else None
        if header:
            outline = Outline(section=header.group(1))
            found.append(Paragraph(outline.section, [], page, text))
            continue
        if outline.section is None:
            continue
        markers = leading_markers(text)
        if not markers and found and found[-1].section == outline.section:
            found[-1].text += " " + text
            continue
        for marker in markers:
            outline.open(marker)
        found.append(Paragraph(outline.section, list(outline.markers), page, text))
    return found


def is_under(child: Paragraph, parent: Paragraph) -> bool:
    return (child.section == parent.section and len(child.markers) > len(parent.markers)
            and child.markers[:len(parent.markers)] == parent.markers)


def stem(paragraph: Paragraph) -> str:
    """ a paragraph's opening sentence, to put a child in context """

    first = re.split(r"(?<=[.?:])\s", paragraph.text, maxsplit=1)[0]
    return first[:240]


def chunks(found: list[Paragraph]) -> list[tuple[Paragraph, str]]:
    """ (paragraph, chunk text) pairs: a paragraph with a short child list is one chunk with its list; any other
        paragraph is its own chunk, opened by its path and its ancestors' stems """

    out, index = [], 0
    while index < len(found):
        paragraph = found[index]
        children = []
        for later in found[index + 1:]:
            if not is_under(later, paragraph):
                break
            children.append(later)
        ancestors = [p for p in found[:index] if is_under(paragraph, p) and p.markers]
        header = f"§ {paragraph.path}\n" + "".join(f"{stem(p)}\n" for p in ancestors)
        whole = paragraph.text + "".join(f"\n{child.text}" for child in children)
        # a section's own header text never absorbs its paragraphs: each first-level paragraph stays citable
        if (paragraph.markers and children and len(whole) <= CHUNK_CHARS
                and all(len(child.text) <= SHORT_CHILD_CHARS for child in children)):
            out.append((paragraph, header + whole))
            index += 1 + len(children)
            continue
        out.append((paragraph, header + paragraph.text))
        index += 1
    return out


def covers(paragraph: str, text: str, provision: str) -> bool:
    """ whether a chunk of this paragraph states the provision: it is the provision or under it, or it is above it and
        holds the provision's own lines (a short child list is chunked whole with its stem) """

    if paragraph == provision or paragraph.startswith(provision + "("):
        return True
    if not provision.startswith(paragraph + "("):
        return False
    deeper = re.findall(r"\(([^)]+)\)", provision[len(paragraph):])
    return all(re.search(rf"(^|\n)\({re.escape(marker)}\)", text) for marker in deeper[-1:])
