"""evaluate_rules runs a worker's rules in one tool round, each on the decisions before it."""

import json

from fieldsight.tools.tools import evaluate_rules

INCIDENT = {
    "incident_id": "inc-1", "work_related": True, "new_case": True, "incident_at": "2026-03-02T09:00:00+00:00",
    "event_at": None, "learned_at": "2026-03-02T09:00:00+00:00", "event_type": "other", "admission_reason": None,
    "amputation_detail": None, "treatments": ["sutures"], "death": False, "days_away": 3, "restricted_days": 0,
    "job_transfer": False, "loss_of_consciousness": False, "significant_diagnosis": False,
    "confidences": {"days_away": 0.95},
}


def run(rule_ids: list[str]):
    command = evaluate_rules.func(rule_ids=rule_ids, state={"incident": INCIDENT, "decisions": {}}, tool_call_id="t1")
    return command, json.loads(command.update["messages"][0].content)["decisions"]


def test_each_rule_sees_the_decisions_before_it():
    command, decisions = run(["R3", "R1", "R4"])

    assert [decisions[rule]["outcome"] for rule in ("R3", "R1", "R4")] == ["beyond_first_aid", "recordable", "H"]
    # every decision goes into the worker's state, as three evaluate_rule calls would have put it
    assert set(command.update["decisions"]) == {"R3", "R1", "R4"}


def test_a_rule_run_out_of_order_is_an_error_for_that_rule_only():
    command, decisions = run(["R4", "R3"])

    assert "error" in decisions["R4"] and decisions["R3"]["outcome"] == "beyond_first_aid"
    assert set(command.update["decisions"]) == {"R3"}


def test_a_citation_by_chunk_id_is_read_as_its_position():
    from fieldsight.schemas.rule_proposal import ClassificationProposal
    from fieldsight.tools.tools import numbered

    proposal = ClassificationProposal.model_validate({
        "outcome": "recordable", "log_column": "J", "day_count": 0, "chunk_ids": ["CFR-1904-d6bf67b0d2f6"],
        "rationale": "R3 applied 1904.7(b)(5)(ii) [CFR-1904-d6bf67b0d2f6]. R4 applied 1904.7(b)(5) [CFR-1904-147835e4d134]. "
                     "Nothing cites [CFR-1904-000000000000]."})
    retrieved = {"CFR-1904-d6bf67b0d2f6": {}, "CFR-1904-147835e4d134": {}}

    fixed = numbered(proposal, retrieved)

    assert fixed.rationale == ("R3 applied 1904.7(b)(5)(ii) [1]. R4 applied 1904.7(b)(5) [2]. "
                               "Nothing cites [CFR-1904-000000000000].")
    # a cited chunk retrieved this run joins chunk_ids; one never retrieved is left for the checks to catch
    assert fixed.chunk_ids == ["CFR-1904-d6bf67b0d2f6", "CFR-1904-147835e4d134"]
