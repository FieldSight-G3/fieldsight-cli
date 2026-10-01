"""A CFR section is chunked by paragraph: each chunk knows its paragraph path, and a short list stays with its stem."""

from fieldsight.ingest.corpus.outline import chunks, covers, paragraphs

ITEMS = [
    (5, "header", "§ 1904.7 General recording criteria."),
    (5, "text", "(a) Basic requirement. You must consider an injury or illness to meet the general recording criteria."),
    (5, "text", "(b) Implementation-(1) How do I decide if a case meets one or more of the general recording criteria?"),
    (5, "text", "(i) Death. See § 1904.7(b)(2)."),
    (5, "text", "(ii) Days away from work. See § 1904.7(b)(3)."),
    (8, "text", "(5) How do I record an injury or illness that involves medical treatment beyond first aid? If a work-related"),
    (8, "text", "injury results in medical treatment beyond first aid, you enter a check mark in the box for such cases."),
    (8, "text", '(ii) What is "first aid"? For the purposes of part 1904, "first aid" means the following:'),
    (8, "text", "(A) Using a non-prescription medication at nonprescription strength;"),
    (8, "text", "(D) Using wound coverings; sutures, staples, etc., are considered medical treatment;"),
    # long, like the real text's later questions, so (b)(5) isn't chunked whole with all its children
    (8, "text", "(iii) Are any other procedures included in first aid? No, this is a complete list. " + "Detail. " * 80),
]


def paths() -> list[str]:
    return [p.path for p in paragraphs(ITEMS)]


def test_the_outline_is_followed_through_headings_roman_numerals_and_lists():
    assert paths() == ["1904.7", "1904.7(a)", "1904.7(b)(1)", "1904.7(b)(1)(i)", "1904.7(b)(1)(ii)", "1904.7(b)(5)",
                       "1904.7(b)(5)(ii)", "1904.7(b)(5)(ii)(A)", "1904.7(b)(5)(ii)(D)", "1904.7(b)(5)(iii)"]


def test_a_paragraph_broken_across_a_page_is_one_paragraph():
    [medical] = [p for p in paragraphs(ITEMS) if p.path == "1904.7(b)(5)"]
    assert "check mark in the box" in medical.text


def test_a_short_list_is_one_chunk_with_its_stem_and_its_path():
    by_path = {paragraph.path: text for paragraph, text in chunks(paragraphs(ITEMS))}
    assert "1904.7(b)(5)(ii)(D)" not in by_path
    first_aid = by_path["1904.7(b)(5)(ii)"]
    assert first_aid.startswith("§ 1904.7(b)(5)(ii)") and "sutures" in first_aid
    # the parent's opening sentence puts the list in context
    assert "How do I record an injury or illness that involves medical treatment beyond first aid?" in first_aid


def test_a_chunk_covers_its_paragraph_its_children_and_a_child_it_holds():
    first_aid = {p.path: t for p, t in chunks(paragraphs(ITEMS))}["1904.7(b)(5)(ii)"]
    assert covers("1904.7(b)(5)(ii)", first_aid, "1904.7(b)(5)(ii)")
    assert covers("1904.7(b)(5)(ii)", first_aid, "1904.7(b)(5)(ii)(D)")
    assert covers("1904.7(b)(5)(ii)(D)", "(D) ...", "1904.7(b)(5)(ii)")
    assert not covers("1904.7(b)(5)", "(5) How do I record ...", "1904.7(b)(5)(ii)")
    assert not covers("1904.7(b)(5)(iii)", "(iii) Are any ...", "1904.7(b)(5)(ii)")
