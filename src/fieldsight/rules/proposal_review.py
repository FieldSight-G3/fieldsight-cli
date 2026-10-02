""" check a specialist's proposal against this run's rule decisions and retrieved chunks; nothing is written """

import re

from ..ingest.corpus.outline import covers
from ..schemas.rule_decision import RuleDecision
from ..schemas.rule_proposal import (
    ClassificationProposal,
    HazardControlProposal,
    Proposal,
    ReportingProposal,
)

# the paragraph of 1910.269(l) each control comes from
CONTROL_PARAGRAPHS = {
    "qualified_employees_only": "1910.269(l)(1)",
    "second_employee_present": "1910.269(l)(2)",
    "minimum_approach_distance": "1910.269(l)(3)",
    "insulation": "1910.269(l)(4)",
    "working_position": "1910.269(l)(5)",
    "connection_sequence": "1910.269(l)(6)",
    "conductive_articles_removed": "1910.269(l)(7)",
    "arc_flash_protection": "1910.269(l)(8)",
    "fuse_handling": "1910.269(l)(9)",
    "covered_conductor_precautions": "1910.269(l)(10)",
    "metal_parts_grounded": "1910.269(l)(11)",
    "load_rated_switching": "1910.269(l)(12)",
}


def problems_with(proposal: Proposal, expected: dict, retrieved: set[str]) -> list[str]:
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


def review_hazard_control(proposal: HazardControlProposal, retrieved: set[str]) -> list[str]:
    """ no rule decides a control, so the citation must resolve: a 1910.269 chunk inside the control's paragraph """

    problems = problems_with(proposal, {}, retrieved)
    if proposal.outcome == "insufficient_data":
        return problems

    if not proposal.chunk_ids or not proposal.chunk_ids[0].startswith("CFR-269-"):
        problems.append("the first chunk id must be the 29 CFR 1910.269 chunk that carries the provision")
    paragraph = CONTROL_PARAGRAPHS[proposal.control_type]
    # the trailing "(" stops (l)(1) from matching (l)(10); the approach-distance tables belong to (l)(3)
    in_paragraph = f"{proposal.provision}(".startswith(f"{paragraph}(")
    in_table = proposal.control_type == "minimum_approach_distance" and proposal.provision.startswith("Table R-")
    if not (in_paragraph or in_table):
        problems.append(f"{proposal.control_type} rests on {paragraph}, not {proposal.provision}")
    return problems


# a sentence that restates a rule decision, and the citations in it
RULE_MENTION = re.compile(r"\bR([1-4])\b")
CITATION = re.compile(r"\[(\d+)\]")
PROVISION = re.compile(r"(\d{4}\.\d+)((?:\([^)]+\))*)")


def grounds(source: str, hit: dict) -> bool:
    """ whether a retrieved chunk states a rule's source provision: a regulation chunk of that paragraph (or of a
        paragraph under it, or a parent chunk holding its lines) """

    found = PROVISION.search(source)
    if found:
        return hit.get("doc_id", "").startswith("CFR-") and covers(
            hit.get("paragraph") or hit.get("section_path", ""), hit.get("text", ""), found.group(1) + found.group(2))
    return False


def rule_citation_problems(proposal: Proposal, decisions: dict[str, dict], retrieved: dict[str, dict]) -> list[str]:
    """ each sentence that restates a rule decision cites a chunk of a provision that rule applied

        A rule decision lists the provisions it applied (its sources). A sentence attributing an outcome to a rule is
        grounded by one of those provisions, at paragraph level, not by whatever a search turned up nearby; the
        problem names the provisions so the worker can read_provision them and cite the result.
    """

    problems = []
    for sentence in re.split(r"(?<=[.!?])\s+", proposal.rationale.strip()):
        rules = list(dict.fromkeys(f"R{n}" for n in RULE_MENTION.findall(sentence) if f"R{n}" in decisions))
        if not rules:
            continue
        sources = list(dict.fromkeys(source for rule in rules for source in decisions[rule].get("sources") or []))
        cited = [proposal.chunk_ids[int(n) - 1] for n in CITATION.findall(sentence) if 0 < int(n) <= len(proposal.chunk_ids)]
        if not any(grounds(source, retrieved.get(chunk_id) or {}) for source in sources for chunk_id in cited):
            problems.append(f'"{sentence[:80]}" restates {"/".join(rules)} but cites no chunk stating a provision it '
                            f"applied: read_provision({sources}) and cite a chunk it returns")
    return problems
