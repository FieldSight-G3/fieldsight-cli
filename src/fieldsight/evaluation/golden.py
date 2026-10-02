""" the golden set: one YAML case per file, and the checks §14 puts on it

    evals/golden/ holds the 15 cases §14's table names. evals/escalation/ holds the paired escalation cases §14
    requires on top of them, and the other side of each threshold boundary; both run in both tiers, and a pair may
    span the two folders. A case is a plain dict, read as written; a missing field is a problem this module
    reports, not a crash in a runner.
"""

from collections import Counter
from pathlib import Path
from typing import Any

import yaml

EVALS = Path(__file__).resolve().parents[3] / "evals"
GOLDEN = EVALS / "golden"
ESCALATION = EVALS / "escalation"

# §14's table: the minimum cases per category
# §14's table: exactly these cases per category in evals/golden/
REQUIRED = {"single_document": 2, "multi_hop": 1, "threshold": 3, "incident_backed": 1, "out_of_corpus": 2,
            "determination_probe": 1, "adversarial": 4, "near_miss": 1}
# §14: one fires-and-doesn't pair for each of these named triggers (the injection pair's "fires" half is adversarial-02)
PAIRED_TRIGGERS = {"field_below_confidence_floor", "rules_engine_insufficient_data", "near_boundary_value",
                   "prompt_attack_detected", "reportable_outcome"}
KNOWN = set(REQUIRED) | {"escalation_pair"}


def load_cases(directory: Path = GOLDEN) -> list[dict[str, Any]]:
    """ every case, in file order; the file name is kept so a problem can name it """

    cases = []
    for path in sorted(directory.glob("*.yaml")):
        case = yaml.safe_load(path.read_text(encoding="utf-8"))
        cases.append({**case, "_file": path.name})
    return cases


def load_all() -> list[dict[str, Any]]:
    """ the golden set and the escalation cases, the set every runner runs """

    return load_cases(GOLDEN) + load_cases(ESCALATION)


def turns(case: dict[str, Any]) -> list[dict[str, Any]]:
    return case.get("turns") or []


def expectations(case: dict[str, Any]) -> list[dict[str, Any]]:
    """ what each turn must do: a turn's own expected block, or the case's for a single-turn case """

    found = [turn.get("expected") for turn in turns(case) if turn.get("expected")]
    if case.get("expected"):
        found.append(case["expected"])
    found += [variant["expected"] for variant in case.get("variants") or [] if variant.get("expected")]
    return found


def case_problems(case: dict[str, Any]) -> list[str]:
    """ what one case is missing from what §14 says every case carries """

    problems = []
    name = case["_file"]
    if case.get("id") != name.removesuffix(".yaml"):
        problems.append(f"{name}: id {case.get('id')!r} doesn't match its file name")
    if case.get("category") not in KNOWN:
        problems.append(f"{name}: unknown category {case.get('category')!r}")
    if not (case.get("why") or "").strip():
        problems.append(f"{name}: no line on why the case exists")
    if not turns(case) and not case.get("threshold"):
        problems.append(f"{name}: no turns to run and no threshold to check")
    if not expectations(case) and not case.get("threshold"):
        problems.append(f"{name}: no expected outcome")

    for expected in expectations(case):
        if expected.get("outcome") == "refusal":
            if not (expected.get("refusal") or {}).get("reason_code"):
                problems.append(f"{name}: a refusal case must carry the refusal reason it should give")
            if not expected.get("must_not_include"):
                problems.append(f"{name}: a refusal case must carry the phrase that must not appear")

    threshold = case.get("threshold")
    if threshold:
        for key in ("rule_id", "boundary", "value", "side", "expected_rule_outcome"):
            if threshold.get(key) is None:
                problems.append(f"{name}: a threshold case must carry {key}")
    return problems


def set_problems(golden: list[dict[str, Any]], extra: list[dict[str, Any]] | None = None) -> list[str]:
    """ the set-level rules: the golden set is §14's table exactly; ids, pairs and paired triggers span both folders """

    extra = extra or []
    cases = golden + extra
    problems = [problem for case in cases for problem in case_problems(case)]

    counts = Counter(case.get("category") for case in golden)
    problems += [f"golden {category}: {counts[category]} case(s), §14's table has {wanted}"
                 for category, wanted in REQUIRED.items() if counts[category] != wanted]
    problems += [f"golden: {case['_file']} is an escalation pair; those go in evals/escalation/"
                 for case in golden if case.get("category") == "escalation_pair"]

    duplicates = [case_id for case_id, n in Counter(case.get("id") for case in cases).items() if n > 1]
    problems += [f"duplicate case id {case_id}" for case_id in duplicates]

    pairs: dict[str, list[dict]] = {}
    for case in cases:
        if case.get("pair_id"):
            pairs.setdefault(case["pair_id"], []).append(case)
    for pair_id, members in pairs.items():
        if len(members) != 2:
            problems.append(f"pair {pair_id}: {len(members)} case(s), a pair is two")
        elif "trigger_fires" in members[0] and members[0].get("trigger_fires") == members[1].get("trigger_fires"):
            problems.append(f"pair {pair_id}: both cases say the trigger {'fires' if members[0]['trigger_fires'] else 'holds'}")

    fired = {(case.get("trigger"), case.get("trigger_fires")) for case in cases if case.get("trigger")}
    for trigger in sorted(PAIRED_TRIGGERS):
        for fires in (True, False):
            if (trigger, fires) not in fired:
                problems.append(f"no case where {trigger} {'fires' if fires else 'does not fire'}")

    if sum(1 for case in golden if len(turns(case)) > 1) < 2:
        problems.append("§14 needs at least two multi-turn cases")
    return problems
