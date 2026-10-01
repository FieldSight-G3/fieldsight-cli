"""The golden set's CI tier (§14): its structure, and every case deterministic code decides, with no model or AWS.

A known failure is xfail(strict): it shows on every run, and the run fails the moment it starts passing, so the
marker is removed on purpose, never left behind.
"""

from uuid import uuid4

import pytest

from fieldsight.evaluation.deterministic import run_case, run_pairs
from fieldsight.evaluation.golden import (
    ESCALATION,
    GOLDEN,
    load_all,
    load_cases,
    set_problems,
)
from fieldsight.evaluation.live import TurnResult, check_turn
from fieldsight.types.escalation import EscalationDecision, EscalationPolicy
from fieldsight.types.run import TurnRun

CASES = load_all()

KNOWN = {
    "escalation-03a": "the case assumes a 7-day near-boundary margin on the 180-day cap (assumed_config); the "
                      "configured log_180d_margin_days is 1 (docs/architecture.md), so 176 days doesn't fire. "
                      "The team decides which one changes.",
}


def test_the_set_meets_section_14():
    assert set_problems(load_cases(GOLDEN), load_cases(ESCALATION)) == []


def test_paired_threshold_cases_come_out_differently():
    assert run_pairs(CASES) == []


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_the_deterministic_expectation_holds(case, request):
    result = run_case(case)
    if result.status == "skipped":
        pytest.skip(result.reason)
    if case["id"] in KNOWN:
        request.applymarker(pytest.mark.xfail(reason=KNOWN[case["id"]], strict=True))
    assert result.problems == []


def turn_run(**fields) -> TurnRun:
    return TurnRun(run_id=uuid4(), correlation_id=uuid4(), command="ask", route="answer_from_retrieval", **fields)


def checked(expected: dict, run: TurnRun, record: dict | None = None) -> TurnResult:
    result = TurnResult("ask", 0.0, 0.0, None)
    check_turn(expected, run, record, [], None, None, result)
    return result


class TestLiveChecks:
    def test_a_retrieval_refusal_counts_as_the_expected_refusal(self):
        run = turn_run(answer="The documents don't cover forklifts.", retrieval_refusal="below_threshold")
        result = checked({"outcome": "refusal", "refusal": {"reason_code": "below_similarity_threshold"},
                          "must_not_include": ["1910.178"]}, run)
        assert result.failed == [] and result.refused is True

    def test_a_forbidden_phrase_fails_case_insensitively(self):
        result = checked({"outcome": "answer", "must_not_include": ["You must report"]},
                         turn_run(answer="you must report this within 8 hours."))
        assert result.failed == ['never says "You must report"']

    def test_a_near_miss_that_refuses_fails(self):
        result = checked({"outcome": "answer", "must_not_refuse": True},
                         turn_run(answer="Not covered.", retrieval_refusal="below_threshold"))
        assert result.failed and result.refused is True

    def test_rule_outcomes_and_triggers_read_the_run_record_and_the_escalation(self):
        record = {"rule_invocations": {"items": [{"decision": {"rule_id": "R2", "outcome": "reportable",
                                                               "inputs": {"event_type": "inpatient_hospitalization"}}}]},
                  "workers_dispatched": {"items": ["recordability", "reportability"]}}
        escalation = EscalationDecision.model_validate({"requires_review": True, "eligible_for_auto_release": False,
                                                        "fired": ["reportable_event"], "checks": {},
                                                        "boundary_observations": [], "policy": EscalationPolicy()})
        expected = {"rule_outcomes": [{"rule_id": "R2", "outcome": "reportable",
                                       "inputs_include": {"event_type": "inpatient_hospitalization"}}],
                    "workers_dispatched": ["recordability", "reportability"],
                    "escalation_triggers_fired": ["reportable_outcome"], "escalated_to_review_queue": True,
                    "demo_artifact": "not a check"}
        result = checked(expected, turn_run(answer="", escalation=escalation), record)
        assert result.failed == [] and result.unchecked == ["demo_artifact"]
