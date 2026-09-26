""" the REPORTABILITY node: run the Reportability Worker and hand back only its proposal and rule invocations """

from datetime import UTC, datetime

from ...prompts import REPORTABILITY_GOAL
from ...schemas.rule_decision import RuleDecision
from ...schemas.rule_proposal import ReportingProposal
from ...schemas.run_records import RuleInvocation
from ..specialists import get_specialists


def reportability_node(state: dict) -> dict:
    """ the proposal is typed so the graph can route on it; None when the worker got none accepted """

    result = get_specialists()["reportability"].invoke({
        "worker": "reportability",
        # the Coordinator narrows the goal when it re-dispatches
        "task": state.get("tasks", {}).get("reportability") or REPORTABILITY_GOAL,
        "incident": state["incident"],
        "messages": [],
        "rounds": 0,
        "decisions": [],
        "retrieved": [],
        "proposal": None,
    })

    proposal = result["proposal"]
    return {
        "reportability": ReportingProposal.model_validate(proposal) if proposal else None,
        # the evaluate_rule tool records its invocations too, like the harness path
        "rule_invocations": [
            RuleInvocation(incident_id=state["incident"]["incident_id"], recorded_at=datetime.now(UTC),
                           decision=RuleDecision.model_validate(decision))
            for decision in result["decisions"]
        ],
    }
