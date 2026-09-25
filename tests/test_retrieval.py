""" the retrieval chain against the requirements for the query pipeline, on a stubbed Knowledge Base """

import pytest
from langchain_core.documents import Document

from fieldsight.retrieval import evidence
from fieldsight.retrieval.grounding import enforce_grounding, refuse
from fieldsight.retrieval.references import pick_filter
from fieldsight.schemas.retrieval import DraftAnswer


def hit(doc_id: str, doc_type: str, section_path: str, text: str) -> Document:
    """ a KB hit shaped the way AmazonKnowledgeBasesRetriever returns one """

    return Document(page_content=text, metadata={"score": 0.8, "source_metadata": {
        "doc_id": doc_id, "title": doc_id, "doc_type": doc_type, "section_path": section_path,
        "page": 1, "chunk_id": f"{doc_id}-{section_path}"}})


REGULATION = hit("CFR-1904", "regulation", "1904.7", "(ii) For the purposes of this part, first aid means the following")
DIRECTIVE = hit("CPL-172", "directive", "IX.E", "The first aid list at 29 CFR 1904.7(b)(5)(ii) is comprehensive.")


@pytest.fixture
def kb(monkeypatch):
    """ a stub KB: (doc_type, section_path) -> hits; every search is recorded """

    results: dict[tuple, list[Document]] = {}
    searches: list[tuple] = []

    def search(query, *, doc_type=None, section_path=None, gated=True):
        searches.append((query, doc_type, section_path))
        return results.get((doc_type, section_path), [])

    monkeypatch.setattr(evidence, "search", search)
    return results, searches


def test_the_question_picks_the_filter():
    assert pick_filter("what does 1904.39 require?")[:2] == ("regulation", "1904.39")
    assert pick_filter("is there a letter of interpretation on paraffin wax?")[:2] == ("interpretation", None)
    assert pick_filter("is a tetanus shot first aid?")[:2] == (None, None)


def test_nothing_above_threshold_is_refused_with_the_escalation_path(kb):
    answer = refuse(evidence.gather({"question": "what are the fall protection rules?"}))

    assert answer.refusal_reason == "below_threshold"
    assert "fall protection" in answer.answer and "review queue" in answer.answer


def test_an_empty_filtered_search_falls_back_to_the_whole_corpus(kb):
    results, searches = kb
    results[(None, None)] = [REGULATION]

    gathered = evidence.gather({"question": "what does the preamble say about first aid?"})

    assert [s[1:] for s in searches] == [("preamble", None), (None, None)]
    assert gathered["refusal"] is None


def test_a_directive_hops_to_the_section_it_construes(kb):
    results, searches = kb
    results[(None, None)] = [DIRECTIVE]
    results[("regulation", "1904.7")] = [REGULATION]

    gathered = evidence.gather({"question": "is a tetanus shot first aid?"})

    assert searches[1][1:] == ("regulation", "1904.7")
    assert gathered["docs"] == [DIRECTIVE, REGULATION]


def test_a_directive_hops_to_the_letter_it_cites(kb):
    results, searches = kb
    results[(None, None)] = [hit("CPL-172", "directive", "IX.P", "See the letter of January 8, 2021.")]

    evidence.gather({"question": "do we report a death after a reported hospitalization?"})

    assert searches[1] == ("Reporting two related reportable events", "interpretation", None)


def grounded(chunk_ids: list[str]):
    return enforce_grounding({"question": "is a tetanus shot first aid?", "docs": [DIRECTIVE, REGULATION],
                              "retrievals": [], "refusal": None,
                              "draft": DraftAnswer(answer="Yes [1].", grounded=True, chunk_ids=chunk_ids)})


def test_citations_resolve_to_the_retrieved_chunks():
    answer = grounded(["CFR-1904-1904.7", "CPL-172-IX.E"])

    assert [s.doc_id for s in answer.sources] == ["CFR-1904", "CPL-172"]


def test_a_citation_to_a_chunk_that_was_not_retrieved_is_refused():
    assert grounded(["CFR-1904-invented"]).refusal_reason == "unresolved_citation"
