"""The ask path: citations by chunk id resolve, a follow-up answers from the analysis's own evidence."""

from langchain_core.documents import Document

from fieldsight.harness.run.answer import answer_question
from fieldsight.retrieval import evidence
from fieldsight.retrieval.grounding import by_position
from fieldsight.schemas.retrieval import DraftAnswer, GroundedAnswer

RETRIEVED = {"CFR-1904-d6bf67b0d2f6": {}, "CFR-1904-147835e4d134": {}}


def test_a_citation_by_chunk_id_becomes_its_position():
    draft = DraftAnswer(answer="Sutures are medical treatment [CFR-1904-d6bf67b0d2f6].", grounded=True,
                        chunk_ids=["CFR-1904-d6bf67b0d2f6"])

    fixed = by_position(draft, RETRIEVED)

    assert fixed.answer == "Sutures are medical treatment [1]." and fixed.chunk_ids == ["CFR-1904-d6bf67b0d2f6"]


def test_a_shortened_chunk_id_resolves_only_when_one_chunk_matches():
    draft = DraftAnswer(answer="The box for medical treatment cases [1].", grounded=True, chunk_ids=["CFR-1904-1478"])
    assert by_position(draft, RETRIEVED).chunk_ids == ["CFR-1904-147835e4d134"]

    ambiguous = DraftAnswer(answer="Something [1].", grounded=True, chunk_ids=["CFR-1904-"])
    assert by_position(ambiguous, RETRIEVED).chunk_ids == ["CFR-1904-"]


def test_a_follow_up_leads_with_the_analysis_citations_even_when_the_search_finds_nothing(monkeypatch):
    monkeypatch.setattr(evidence, "search", lambda *args, **kwargs: [])
    seed = [{"chunk_id": "CFR-1904-147835e4d134", "doc_id": "CFR-1904", "section_path": "1904.7", "title": "Part 1904",
             "text": "(5) ... you enter a check mark in the box for cases where the employee received medical treatment"}]

    out = evidence.gather({"question": "Why the medical treatment column?", "seed": seed})

    assert out["refusal"] is None
    assert [doc.metadata["source_metadata"]["chunk_id"] for doc in out["docs"]] == ["CFR-1904-147835e4d134"]
    # recorded as retrieved this turn, which the answer guard's citation check requires
    assert "CFR-1904-147835e4d134" in out["retrievals"][0].scores


def test_answer_question_hands_the_seed_to_every_draft():
    seen = []

    def answerer(question, objections, seed=None):
        seen.append(seed)
        return GroundedAnswer(question=question, answer="", grounded=False, refusal_reason="not_grounded",
                              escalation="queue")

    answer_question("why?", answerer, incident=None, rule_invocations=[], correlation_id="c", seed=[{"chunk_id": "x"}])

    assert seen == [[{"chunk_id": "x"}]]


def test_a_document_seeded_without_text_is_skipped():
    assert evidence.seeded("q", [{"chunk_id": "x"}], []) == []
    assert isinstance(evidence.seeded("q", [{"chunk_id": "x", "text": "t"}], [])[0], Document)
