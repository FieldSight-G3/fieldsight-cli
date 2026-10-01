"""The answer path: a retry that comes back refused is the answer, and a follow-up reuses what the analysis recorded."""

from datetime import UTC, datetime

from fieldsight.harness.run import answer
from fieldsight.schemas.retrieval import Citation, GroundedAnswer, Retrieval
from fieldsight.schemas.rule_decision import RuleDecision
from fieldsight.schemas.run_records import RuleInvocation

SOURCE = Citation(doc_id="CFR-1904", title="Part 1904", section_path="1904.39", chunk_id="CFR-1904-a")


def grounded(text: str) -> GroundedAnswer:
    searched = Retrieval(query="q", reason="the question", scores={SOURCE.chunk_id: 0.8})
    return GroundedAnswer(question="q", answer=text, grounded=True, sources=[SOURCE], retrievals=[searched])


def refused() -> GroundedAnswer:
    return GroundedAnswer(question="q", answer="The retrieved passages don't answer this question.", grounded=False,
                          refusal_reason="not_grounded", retrievals=[])


def test_a_retry_that_comes_back_refused_is_returned_as_that_refusal():
    drafts = iter([grounded("An uncited claim."), refused()])

    result = answer.answer_question("q", lambda question, objections: next(drafts), incident=None, rule_invocations=[],
                                    correlation_id="c")

    assert result["refusal"] is None and result["retrieval_refusal"] == "not_grounded"


def test_a_follow_up_attributes_thresholds_to_the_recorded_decision_without_reading_the_question(monkeypatch):
    monkeypatch.setattr(answer, "question_facts", lambda question, incident_id: (_ for _ in ()).throw(AssertionError()))
    recorded = RuleInvocation(incident_id="i", recorded_at=datetime.now(UTC), decision=RuleDecision(
        rule_id="R2", outcome="not_reportable", inputs={}, sources=["29 CFR 1904.39(b)(10)"]))

    result = answer.answer_question("why isn't this reportable?",
                                    lambda question, objections: grounded("R2 found it is not reportable [1]."),
                                    incident=None, rule_invocations=[recorded], correlation_id="c", about_incident=True)

    assert result["refusal"] is None and result["rule_invocations"] == [recorded]
