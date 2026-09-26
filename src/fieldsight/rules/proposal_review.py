""" check a specialist's proposal against this run's rule decisions and retrieved chunks; nothing is written """

from ..schemas.rule_decision import RuleDecision
from ..schemas.rule_proposal import ClassificationProposal, ReportingProposal


def problems_with(proposal: ClassificationProposal | ReportingProposal, expected: dict, retrieved: set[str]) -> list[str]:
    """ every field that doesn't match the rules, and every citation that wasn't retrieved this run """

    problems = [f"{field} must be {value}" for field, value in expected.items() if getattr(proposal, field) != value]
    if not proposal.chunk_ids and proposal.outcome != "insufficient_data":
        problems.append("cite at least one chunk from search_knowledge_base")
    return problems + [f"{chunk_id} wasn't retrieved this run" for chunk_id in proposal.chunk_ids if chunk_id not in retrieved]


def review_classification(proposal: ClassificationProposal, decisions: dict[str, dict], retrieved: set[str]) -> list[str]:
    """ outcome and missing field from R1; column, day count and missing field from R4 when recordable """

    if "R1" not in decisions:
        return ["evaluate R1 first"]
    r1 = RuleDecision.model_validate(decisions["R1"])
    expected = {"outcome": r1.outcome, "missing_field": r1.missing_field, "log_column": None, "day_count": None}

    if r1.outcome == "recordable":
        if "R4" not in decisions:
            return ["evaluate R4 for the 300-Log column first"]
        r4 = RuleDecision.model_validate(decisions["R4"])
        expected |= {"missing_field": r4.missing_field, "log_column": r4.log_column, "day_count": r4.day_count}
    return problems_with(proposal, expected, retrieved)


def review_reporting(proposal: ReportingProposal, decisions: dict[str, dict], retrieved: set[str]) -> list[str]:
    """ outcome, clock, deadline, exclusion and missing field all from R2 """

    if "R2" not in decisions:
        return ["evaluate R2 first"]
    r2 = RuleDecision.model_validate(decisions["R2"])
    clock = None
    if r2.outcome == "reportable":
        clock = 8 if r2.inputs.get("event_type") == "fatality" else 24

    # R2 names any exclusion it applied, so a proposal that stops at the clock is rejected here
    return problems_with(proposal, {"outcome": r2.outcome, "clock_hours": clock, "deadline": r2.deadline,
                                    "exclusion": r2.exclusion, "missing_field": r2.missing_field}, retrieved)
