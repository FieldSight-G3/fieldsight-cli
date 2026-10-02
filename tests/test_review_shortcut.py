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
