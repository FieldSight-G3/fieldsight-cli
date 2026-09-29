""" one assembled turn: the Coordinator's graph and the retrieval chain behind run_turn

    The CLI and the AgentCore Runtime both call turn(), so there is one composition of the system, not two.
    The graph's final state becomes a WorkflowResult here, and stage 4 (guard_dossier) runs on that dossier
    before run_turn evaluates escalation and saves the turn.
"""

import logging
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from ..config import settings
from ..graph.graph import run_graph
from ..harness.bounds import BoundsConfig, SessionUsage, TurnUsage
from ..harness.bounds_runtime import BoundStopped
from ..harness.guardrails.common import refuse
from ..harness.guardrails.dossier_guard import guard_dossier
from ..harness.metering.meter import metered
from ..harness.metering.pricing import PricingConfig
from ..harness.run.answer import Answerer
from ..harness.run.lifecycle import run_turn
from ..harness.run.workflow import Workflow
from ..repository import IncidentRepository
from ..schemas.incidents import NormalizedIncident
from ..security.entitlement import require_grant
from ..types.run import TurnRun, WorkflowResult

logger = logging.getLogger(__name__)

GraphRunner = Callable[[UUID, NormalizedIncident, str | None], dict]


def _approved(verdict: Any) -> bool:
    """ a verdict from the checkpoint can come back as a model or a plain dict """

    if verdict is None:
        return False
    return bool(verdict.get("approved") if isinstance(verdict, dict) else verdict.approved)


def workflow_result(state: dict, incident: NormalizedIncident, correlation_id: str) -> WorkflowResult:
    """ the graph's final state as the harness reads it, with stage 4 applied to the dossier """

    dossier = dict(state.get("dossier") or {})
    workers = list(dict.fromkeys(d["worker"] for plan in state.get("plans") or [] for d in plan.get("dispatches", [])))
    reviews = state.get("reviews") or []
    guarded = guard_dossier(dossier, incident=incident, rule_invocations=[], correlation_id=correlation_id)
    # only what was actually retrieved; no cited hits means retrieval is unevaluated, not failed
    scores = [hit["score"] for leg in dossier.values() for hit in (leg.get("cited") or {}).values() if "score" in hit]
    return WorkflowResult(
        dossier=dossier,
        workers_dispatched=workers,
        rule_invocations=guarded["rule_invocations"],
        reviewer_approved=_approved(reviews[-1]) if reviews else None,
        reviewer_iterations=state.get("review_iterations"),
        citations_supported=guarded["citations_supported"],
        blocked=guarded["blocked"],
        retrieval_scores=scores or None,
        events=guarded["events"],
    )


def graph_workflow(analyst_id: UUID, *, run: GraphRunner = run_graph) -> Workflow:
    """ the run_workflow route for this analyst: the graph on the stored narrative, read back as a WorkflowResult

        The graph takes no question yet, so an ask that runs the workflow re-plans from the narrative alone.
    """

    def workflow(incident: NormalizedIncident, question: str | None, correlation_id: str) -> WorkflowResult:
        stored = IncidentRepository().get(UUID(incident.incident_id))
        try:
            state = run(analyst_id, incident, stored.narrative if stored else None)
        except BoundStopped:
            # the meter refused the next model call: the turn still ends, is recorded, and names the ceiling
            return WorkflowResult(dossier={})
        return workflow_result(state, incident, correlation_id)

    return workflow


def rag_answerer(chain: Any = None) -> Answerer:
    """ the retrieval chain as run_turn's answerer; a regeneration carries the guard's objections into the question """

    built: list[Any] = [chain]

    def answer(question: str, objections: list[str]) -> Any:
        if built[0] is None:
            from ..retrieval.chain import build_rag_chain

            built[0] = build_rag_chain()
        if objections:
            question += "\n\nYour previous answer was refused. Fix these before answering again:\n" + "\n".join(f"- {o}" for o in objections)
        return built[0].invoke({"question": question})

    return answer


def turn(raw: dict, *, analyst_id: UUID | str, cracked: dict[str, str] | None = None, usage: SessionUsage | None = None,
         run: GraphRunner = run_graph, answerer: Answerer | None = None, limits: BoundsConfig | None = None,
         pricing: PricingConfig | None = None) -> TurnRun:
    """ one command as the verified analyst; raises ToolDenied before anything is read if they hold no grant

        Every model call is metered against the session's cost ceiling and the turn's wall clock. The returned
        TurnRun's usage carries the session's spend, including this turn's, for the next turn to start from.
    """

    analyst = UUID(str(analyst_id))
    incident_id = raw.get("incident_id")
    try:
        incident = UUID(str(incident_id).strip()) if incident_id is not None else None
    except ValueError:
        incident = None
    if incident is not None:
        require_grant(analyst, incident)
    limits = limits or settings.bounds
    start = SessionUsage(session_id=usage.session_id if usage else str(incident or analyst),
                         incident_id=usage.incident_id if usage else incident or UUID(int=0),
                         cost_usd=usage.cost_usd if usage else Decimal(0), turn=TurnUsage(turn_id=str(uuid4())))
    with metered(start, limits, pricing) as meter:
        result = run_turn(raw, workflow=graph_workflow(analyst, run=run), answerer=answerer or rag_answerer(),
                          cracked=cracked, usage=usage, limits=limits, analyst_id=analyst)
    for call in meter.calls:
        logger.info("model call priced", extra={"model_id": call.model_id, "input_tokens": call.input_tokens,
                                               "output_tokens": call.output_tokens, "cost_usd": str(call.cost_usd),
                                               "seconds": round(call.seconds, 3), "run_id": str(result.run_id)})
    update: dict[str, Any] = {}
    if result.usage is not None:
        update["usage"] = result.usage.model_copy(update={"cost_usd": result.usage.cost_usd + meter.spent_this_turn})
    if meter.stopped is not None and result.refusal is None:
        update["refusal"] = refuse("bound_reached", f"This session's {meter.stopped.reason_code} limit ({meter.stopped.limit}) is spent.")
    return result.model_copy(update=update) if update else result
