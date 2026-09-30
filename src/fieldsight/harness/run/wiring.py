""" one assembled turn: the Coordinator's graph and the retrieval chain behind run_turn, and a packet's submit

    The CLI and the AgentCore Runtime both call turn(), so there is one composition of the system, not two.
    The Coordinator's graph (graph.graph_workflow) runs stage 4 in its eligibility check and hands back a
    WorkflowResult; run_turn then evaluates escalation and saves the turn.
"""

import logging
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ...config import settings
from ...graph.graph import graph_workflow
from ...ingest.submit import ingest_packet, packet_artifacts
from ...repository import IncidentRepository, RunRecordRepository
from ...schemas.incidents import NormalizedIncident
from ...security.entitlement import require_grant, submit_establishment
from ...types.artifacts import SubmitResult
from ...types.run import TurnRun, WorkflowResult
from ..bounds import BoundsConfig, SessionUsage, TurnUsage
from ..bounds_runtime import BoundStopped
from ..guardrails.common import refuse
from ..guardrails.turn_check import check_turn
from ..metering.meter import metered
from ..metering.pricing import PricingConfig
from .answer import Answerer
from .lifecycle import run_turn
from .workflow import Workflow

logger = logging.getLogger(__name__)

def harness_workflow(workflow: Workflow) -> Workflow:
    """ the graph's workflow as the harness runs it: a meter refusal ends the turn instead of raising, and the cited
        hits' scores go to escalation's retrieval trigger """

    def run(incident: NormalizedIncident, question: str | None, correlation_id: str) -> WorkflowResult:
        try:
            result = workflow(incident, question, correlation_id)
        except BoundStopped:
            # the meter refused the next model call: the turn still ends, is recorded, and names the ceiling
            return WorkflowResult(dossier={})
        # only what was actually retrieved; no cited hits means retrieval is unevaluated, not failed
        scores = [hit["score"] for leg in result.dossier.values() for hit in (leg.get("cited") or {}).values() if "score" in hit]
        return result.model_copy(update={"retrieval_scores": scores or None})

    return run


def rag_answerer(chain: Any = None) -> Answerer:
    """ the retrieval chain as run_turn's answerer; a regeneration carries the guard's objections into the question """

    built: list[Any] = [chain]

    def answer(question: str, objections: list[str]) -> Any:
        if built[0] is None:
            from ...retrieval.chain import build_rag_chain

            built[0] = build_rag_chain()
        if objections:
            question += "\n\nYour previous answer was refused. Fix these before answering again:\n" + "\n".join(f"- {o}" for o in objections)
        return built[0].invoke({"question": question})

    return answer


def turn(raw: dict, *, analyst_id: UUID | str, cracked: dict[str, str] | None = None, usage: SessionUsage | None = None,
         workflow: Workflow | None = None, answerer: Answerer | None = None, limits: BoundsConfig | None = None,
         pricing: PricingConfig | None = None) -> TurnRun:
    """ one command as the verified analyst; raises ToolDenied before anything is read if they hold no grant

        Every model call is metered against the session's cost ceiling and the turn's wall clock. The returned
        TurnRun's usage carries the session's spend, including this turn's, for the next turn to start from.
        workflow defaults to the Coordinator's graph for this analyst; tests pass a stand-in.
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
        result = run_turn(raw, workflow=harness_workflow(workflow or graph_workflow(analyst)), answerer=answerer or rag_answerer(),
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


def submit(folder: Path, *, analyst_id: UUID | str, limits: BoundsConfig | None = None,
           pricing: PricingConfig | None = None) -> SubmitResult:
    """ one packet in as the verified analyst, filed under their most recent grant and owned by them

        Stage 1 runs before anything is uploaded; stage 2 screens every cracked string before redaction and the
        model; the normalize call is metered like any other. Raises ToolDenied if the analyst holds no grant.
    """

    analyst = UUID(str(analyst_id))
    establishment = submit_establishment(analyst)
    correlation_id = uuid4()
    supported, skipped = packet_artifacts(folder)
    raw = {"command": "submit", "incident_id": folder.name,
           "artifacts": [{"name": path.name, "size_bytes": path.stat().st_size} for path in supported]}
    validated = check_turn(raw, incident=None, cracked={}, correlation_id=str(correlation_id))
    if validated["refusal"]:
        return SubmitResult(incident_id=None, establishment=establishment, report=None, withheld=[], photos=[],
                            refusal=validated["refusal"])

    def screen(cracked: dict[str, str]) -> dict[str, str]:
        return check_turn(raw, incident=None, cracked=cracked, correlation_id=str(correlation_id))["texts"]

    start = SessionUsage(session_id=str(analyst), incident_id=UUID(int=0), turn=TurnUsage(turn_id=str(correlation_id)))
    with metered(start, limits or settings.bounds, pricing):
        packet = ingest_packet(supported, skipped, screen=screen)
    incident_id = IncidentRepository().create(establishment, packet["incident"].model_dump(mode="json", exclude={"incident_id"}),
                                              packet["narrative"], owner_analyst_id=analyst)
    RunRecordRepository().create(correlation_id, "submit", incident_id=incident_id)
    return SubmitResult(incident_id=str(incident_id), establishment=establishment, report=packet["report"],
                        withheld=packet["withheld"], photos=packet["photos"], refusal=None)
