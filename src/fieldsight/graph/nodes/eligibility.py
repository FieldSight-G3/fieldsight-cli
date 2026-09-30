""" the eligibility check: stage 4 (guard_dossier) on the reviewed dossier, where the graph hands the finished cycle back

    It writes nothing. run_turn evaluates escalation over the whole turn and saves once: the run record, and the
    review queue row with its dossier snapshot when a trigger fired.
"""

from datetime import UTC, datetime

from ...harness.guardrails.dossier_guard import guard_dossier
from ...schemas.incidents import NormalizedIncident
from ...schemas.run_records import RuleInvocation


def eligibility_check_node(state: dict) -> dict:
    """ stage 4 on the reviewed dossier; escalation and the run record happen in run_turn once the graph returns """

    incident = NormalizedIncident.model_validate(state["incident"])
    dossier = state.get("dossier") or {}
    # the workers' own evaluate_rule results; §6 says the tool path records an invocation too
    worker_rules = [RuleInvocation(incident_id=incident.incident_id, recorded_at=datetime.now(UTC), decision=decision)
                    for leg in dossier.values() for decision in leg["decisions"].values()]
    return guard_dossier(dossier, incident=incident, rule_invocations=worker_rules,
                         correlation_id=state["correlation_id"])