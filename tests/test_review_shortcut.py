"""With no proposal in any dispatched leg there is nothing to judge, so the Reviewer's model isn't called."""

from fieldsight.graph.nodes import review
from fieldsight.prompts import GOALS


def leg(proposal):
    return {"task": "t", "proposal": proposal, "decisions": {}, "cited": {}}


def test_no_proposal_anywhere_is_rejected_without_a_model_call(monkeypatch):
    monkeypatch.setattr(review, "get_reviewer", lambda: (_ for _ in ()).throw(AssertionError("the model was called")))
    state = {"analyst_id": "a", "incident": {"incident_id": "i"}, "dossier": {"recordability": leg(None)}}

    out = review.reviewer_node(state)

    [verdict] = out["reviews"]
    assert verdict.approved is False and [r.worker for r in verdict.rejections] == ["recordability"]
    assert out["review_iterations"] == 1 and out["model_calls"] == []
    assert out["tasks"] == {"recordability": GOALS["recordability"]}


def test_a_finished_leg_still_gets_a_real_review():
    assert review.no_proposals({"dossier": {"recordability": leg({"rationale": "r"}), "reportability": leg(None)}}) is None


def test_the_reviewer_is_shown_which_rule_sentences_the_check_verified():
    r4 = {"rule_id": "R4", "outcome": "J", "sources": ["29 CFR 1904.7(b)(5)"]}
    chunk = {"doc_id": "CFR-1904", "section_path": "1904.7", "paragraph": "1904.7(b)(5)",
             "text": "(5) How do I record an injury or illness that involves medical treatment beyond first aid?"}
    proposal = {"rationale": "R4 selected the box for medical treatment cases under 1904.7(b)(5) [1]. "
                             "R4 also said something uncited.", "chunk_ids": ["reg-b5"]}

    found = review.verified({"recordability": {"proposal": proposal, "decisions": {"R4": r4}, "cited": {"reg-b5": chunk}}})

    # only the sentence whose citation states a provision R4 applied is vouched for
    assert found == {"recordability": [{"sentence": "R4 selected the box for medical treatment cases under 1904.7(b)(5) [1].",
                                        "rules": ["R4"], "grounded_by": "29 CFR 1904.7(b)(5)"}]}
