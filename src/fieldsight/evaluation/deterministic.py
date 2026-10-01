""" the CI tier (§14): every golden case whose expected outcome is decided by deterministic code, run without a model

    A threshold block's rule_inputs go straight into its rule; an escalation pair's named trigger is evaluated by the
    harness's own trigger code over an incident built from those inputs. A case that needs a packet, a model or a
    database is the live tier's, and is reported as skipped here, never as passed.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from ..harness.escalation.triggers import evaluate_escalation
from ..rules.confidence import confidence_floor
from ..rules.engine import evaluate_incident
from ..rules.log_classification import log_classification
from ..rules.recordability import recordability
from ..rules.reporting import reporting_clock
from ..rules.treatment import medical_treatment
from ..schemas.incidents import NormalizedIncident
from ..schemas.rule_input import R1Inputs, R2Inputs, R3Inputs, R4Inputs, R5Inputs
from ..types.escalation import EscalationPolicy

RULES = {"R1": (R1Inputs, recordability), "R2": (R2Inputs, reporting_clock), "R3": (R3Inputs, medical_treatment),
         "R4": (R4Inputs, log_classification), "R5": (R5Inputs, confidence_floor)}

# the golden set's trigger names, as the harness names them in an EscalationDecision
TRIGGERS = {"field_below_confidence_floor": "confidence_gate", "rules_engine_insufficient_data": "insufficient_data",
            "near_boundary_value": "near_boundary", "prompt_attack_detected": "prompt_attack",
            "reportable_outcome": "reportable_event"}
# a trigger CI can evaluate from rule inputs alone; the others need a packet or a model (the live tier)
FROM_INPUTS = {"near_boundary_value"}

Status = Literal["passed", "failed", "skipped"]


@dataclass
class CaseResult:
    case_id: str
    status: Status
    checks: list[str] = field(default_factory=list)    # what was asserted
    problems: list[str] = field(default_factory=list)  # what didn't hold
    reason: str = ""                                   # why a case was skipped


def _rule(threshold: dict[str, Any]) -> dict[str, Any]:
    schema, rule = RULES[threshold["rule_id"]]
    return rule(schema.model_validate(threshold["rule_inputs"])).model_dump(mode="json")


def _same_time(expected: str, actual: str | None) -> bool:
    return actual is not None and datetime.fromisoformat(expected) == datetime.fromisoformat(actual)


def check_threshold(threshold: dict[str, Any]) -> tuple[list[str], list[str]]:
    """ the rule over the case's inputs: its outcome, and the deadline and day count when the case names them """

    decision = _rule(threshold)
    rule, checks, problems = threshold["rule_id"], [], []
    checks.append(f"{rule} -> {threshold['expected_rule_outcome']}")
    if decision["outcome"] != threshold["expected_rule_outcome"]:
        problems.append(f"{rule} returned {decision['outcome']}, expected {threshold['expected_rule_outcome']}")
    if threshold.get("expected_deadline"):
        checks.append(f"{rule} deadline {threshold['expected_deadline']}")
        if not _same_time(threshold["expected_deadline"], decision.get("deadline")):
            problems.append(f"{rule} deadline {decision.get('deadline')}, expected {threshold['expected_deadline']}")
    if threshold.get("expected_day_count") is not None:
        checks.append(f"{rule} day count {threshold['expected_day_count']}")
        if decision.get("day_count") != threshold["expected_day_count"]:
            problems.append(f"{rule} day count {decision.get('day_count')}, expected {threshold['expected_day_count']}")
    return checks, problems


def _incident(rule_inputs: dict[str, Any]) -> NormalizedIncident:
    """ a recordable, fully confident incident carrying the case's R4 inputs, so only the case's value is in question """

    return NormalizedIncident.model_validate({
        "incident_id": "00000000-0000-0000-0000-000000000000", "work_related": True, "new_case": True,
        "incident_at": None, "event_at": None, "learned_at": None, "event_type": "other",
        "admission_reason": None, "amputation_detail": None,
        "treatments": [], "loss_of_consciousness": False, "significant_diagnosis": False,
        "death": rule_inputs.get("death", False), "days_away": rule_inputs.get("days_away", 0),
        "restricted_days": rule_inputs.get("restricted_days", 0), "job_transfer": rule_inputs.get("job_transfer", False),
        "confidences": {"days_away": 0.95, "restricted_days": 0.95},
    })


def check_trigger(case: dict[str, Any], policy: EscalationPolicy) -> tuple[list[str], list[str]]:
    """ the harness's trigger evaluation over an incident with the case's value: does the named trigger fire? """

    name = TRIGGERS[case["trigger"]]
    incident = _incident(case["threshold"]["rule_inputs"])
    decision = evaluate_escalation(incident, evaluate_incident(incident), policy=policy)
    fired = decision.checks[name].fired
    expected = case["trigger_fires"]
    check = f"{name} {'fires' if expected else 'holds'} at {case['threshold']['value']}"
    problem = [] if fired == expected else [(
        f"{name} {'fired' if fired else 'did not fire'} at {case['threshold']['value']}, expected it to "
        f"{'fire' if expected else 'hold'} (margin: {decision.checks[name].details or 'none near'})")]
    return [check], problem


def run_case(case: dict[str, Any], policy: EscalationPolicy | None = None) -> CaseResult:
    """ one case's deterministic checks, or skipped with the reason """

    policy = policy or EscalationPolicy()
    threshold = case.get("threshold")
    if not threshold or not threshold.get("rule_inputs"):
        return CaseResult(case["id"], "skipped", reason="needs a packet or a model: live tier")
    if threshold["rule_id"] not in RULES:
        return CaseResult(case["id"], "skipped", reason=f"no deterministic rule {threshold['rule_id']}")

    checks, problems = check_threshold(threshold)
    if case.get("trigger") in FROM_INPUTS:
        more_checks, more_problems = check_trigger(case, policy)
        checks += more_checks
        problems += more_problems
    return CaseResult(case["id"], "failed" if problems else "passed", checks, problems)


def run_pairs(cases: list[dict[str, Any]]) -> list[str]:
    """ §14: paired threshold cases must come out differently, outcome or day count """

    problems = []
    pairs: dict[str, list[dict]] = {}
    for case in cases:
        if case.get("category") == "threshold" and case.get("pair_id"):
            pairs.setdefault(case["pair_id"], []).append(case)
    for pair_id, members in pairs.items():
        if len(members) == 2:
            first, second = (_rule(member["threshold"]) for member in members)
            if (first["outcome"], first.get("day_count"), first.get("deadline")) == \
               (second["outcome"], second.get("day_count"), second.get("deadline")):
                problems.append(f"pair {pair_id}: both sides of the boundary come out the same ({first['outcome']})")
    return problems
