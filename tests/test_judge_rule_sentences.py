"""A dossier sentence crediting an outcome to a rule is judged against the rule decisions and the chunk together."""

from fieldsight.evaluation import judge

DECISIONS = {"R3": {"rule_id": "R3", "outcome": "beyond_first_aid", "inputs": {"treatments": ["burn_treatment"]}}}


def asked(monkeypatch) -> list[tuple[str, str]]:
    seen = []
    monkeypatch.setattr(judge, "_ask", lambda schema, system, human: seen.append((system, human)))
    return seen


def test_a_rule_sentence_with_decisions_gets_the_two_source_check(monkeypatch):
    seen = asked(monkeypatch)

    judge.groundedness("R3 found burn treatment beyond first aid under 1904.7(b)(5)(ii) [1].", "(ii) first aid means", DECISIONS)

    [(system, human)] = seen
    assert system == judge.RULE_GROUNDEDNESS
    assert '"beyond_first_aid"' in human and "(ii) first aid means" in human


def test_a_plain_sentence_or_a_missing_record_keeps_the_chunk_only_check(monkeypatch):
    seen = asked(monkeypatch)

    judge.groundedness("Section 1904.7 covers days away [1].", "chunk", DECISIONS)
    judge.groundedness("R3 found burn treatment beyond first aid [1].", "chunk", None)

    assert [system for system, _ in seen] == [judge.GROUNDEDNESS, judge.GROUNDEDNESS]
