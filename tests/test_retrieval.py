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


# whether each search in the current test was gated, in order
gates: list[bool] = []


@pytest.fixture
def kb(monkeypatch):
    """ a stub KB: (doc_type, section_path) -> hits; every search is recorded """

    results: dict[tuple, list[Document]] = {}
    searches: list[tuple] = []
    gates.clear()

    def search(query, *, doc_type=None, section_path=None, gated=True):
        searches.append((query, doc_type, section_path))
        gates.append(gated)
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

    # the filtered search, then the whole corpus; diversifying that unfiltered search may follow
    assert [s[1:] for s in searches][:2] == [("preamble", None), (None, None)]
    assert gathered["refusal"] is None


def test_a_directive_hops_to_the_section_it_construes(kb):
    results, searches = kb
    results[(None, None)] = [DIRECTIVE]
    results[("regulation", "1904.7")] = [REGULATION]

    gathered = evidence.gather({"question": "is a tetanus shot first aid?"})

    assert ("regulation", "1904.7") in [s[1:] for s in searches]
    assert gathered["docs"] == [DIRECTIVE, REGULATION]


def test_a_directive_hops_to_the_letter_it_cites(kb):
    results, searches = kb
    results[(None, None)] = [hit("CPL-172", "directive", "IX.P", "See the letter of January 8, 2021.")]

    evidence.gather({"question": "do we report a death after a reported hospitalization?"})

    assert ("Reporting two related reportable events", "interpretation", None) in searches


def grounded(chunk_ids: list[str]):
    return enforce_grounding({"question": "is a tetanus shot first aid?", "docs": [DIRECTIVE, REGULATION],
                              "retrievals": [], "refusal": None,
                              "draft": DraftAnswer(answer="Yes [1].", grounded=True, chunk_ids=chunk_ids)})


def test_citations_resolve_to_the_retrieved_chunks():
    answer = grounded(["CFR-1904-1904.7", "CPL-172-IX.E"])

    assert [s.doc_id for s in answer.sources] == ["CFR-1904", "CPL-172"]


def test_a_citation_to_a_chunk_that_was_not_retrieved_is_refused():
    assert grounded(["CFR-1904-invented"]).refusal_reason == "unresolved_citation"


def test_a_citation_numbered_by_the_excerpts_shown_is_read_that_way():
    # two excerpts shown, one chunk id listed, and [2] cited: the model counted the excerpts, not its own list
    answer = enforce_grounding({"question": "is a tetanus shot first aid?", "docs": [DIRECTIVE, REGULATION],
                                "retrievals": [], "refusal": None,
                                "draft": DraftAnswer(answer="Yes [2].", grounded=True, chunk_ids=["CPL-172-IX.E"])})
    assert answer.refusal_reason is None and answer.sources[1].doc_id == "CFR-1904"


def test_a_draft_the_model_never_structured_is_refused_not_a_crash():
    answer = enforce_grounding({"question": "is a tetanus shot first aid?", "docs": [DIRECTIVE], "retrievals": [],
                                "refusal": None, "draft": None})
    assert answer.refusal_reason == "not_grounded"


def test_a_hop_takes_the_cited_sections_best_chunks_without_the_threshold(kb):
    # the first search decides coverage; a hop's chunks are relevant because they're cited, so its gate is off and
    # it keeps at most HOP_CHUNKS of them
    results, _ = kb
    results[(None, None)] = [DIRECTIVE]
    results[("regulation", "1904.7")] = [hit("CFR-1904", "regulation", "1904.7", f"part {n}") for n in range(5)]
    for n, doc in enumerate(results[("regulation", "1904.7")]):
        doc.metadata["source_metadata"]["chunk_id"] = f"CFR-1904-1904.7-{n}"

    gathered = evidence.gather({"question": "is a tetanus shot first aid?"})

    # the first search and the per-type ones are gated; only the hop is not
    assert gates[0] is True and gates[-1] is False and gates.count(False) == 1
    assert len([doc for doc in gathered["docs"] if doc.metadata["source_metadata"]["doc_id"] == "CFR-1904"]) == evidence.HOP_CHUNKS


LETTER = hit("LOI-PACK", "interpretation", "2021-01-08", "Two related reportable events are reported once.")


def test_an_unfiltered_search_adds_the_best_chunk_of_each_type_it_missed(kb):
    results, searches = kb
    results[(None, None)] = [REGULATION]
    results[("interpretation", None)] = [LETTER]

    gathered = evidence.gather({"question": "is a tetanus shot first aid?"})

    assert LETTER in gathered["docs"]
    # every type the first search missed was searched; one with nothing above the threshold doesn't count as a gap
    assert {s[1] for s in searches[1:6]} == {"directive", "preamble", "interpretation", "form"}
    assert all(r.superseded for r in gathered["retrievals"] if r.reason.startswith("the best") and not r.scores)


def test_a_filtered_search_is_not_diversified(kb):
    results, searches = kb
    results[("regulation", "1904.39")] = [REGULATION]

    evidence.gather({"question": "what does 1904.39 require?"})

    assert [s[1:] for s in searches] == [("regulation", "1904.39")]



def test_a_retrieved_letter_chunk_brings_the_rest_of_its_letter(kb):
    # a letter's restatement of the question matched; OSHA's answer is in the letter's next chunk
    results, searches = kb
    question_part = hit("LOI-PACK", "interpretation", "2021-01-08", "You ask whether two related events are reported twice.")
    answer_part = hit("LOI-PACK", "interpretation", "2021-01-08", "It is not OSHA's intention that they be reported twice.")
    answer_part.metadata["source_metadata"]["chunk_id"] = "LOI-PACK-2021-01-08-answer"
    results[(None, None)] = [question_part]
    results[("interpretation", "2021-01-08")] = [question_part, answer_part]

    gathered = evidence.gather({"question": "do we report a death after a reported hospitalization?"})

    assert answer_part in gathered["docs"]
    assert ("interpretation", "2021-01-08") in [s[1:] for s in searches]
