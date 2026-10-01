""" one turn, start to finish: stages 1 to 3, the workflow or a retrieval answer, escalation, and the run record """

from uuid import UUID, uuid4

from ...config import settings
from ...repository import RunRepository
from ...rules.engine import evaluate_incident
from ...schemas.incidents import NormalizedIncident
from ...schemas.run_records import RuleInvocation
from ...types.escalation import EscalationPolicy, EscalationSignals
from ...types.run import TurnRun
from ..bounds import SessionUsage, TurnUsage, start_turn
from ..escalation.snapshot import ReviewSnapshot
from ..escalation.triggers import evaluate_escalation
from ..guardrails.turn_check import check_turn
from ..metering.meter import ModelCall as MeteredCall
from .answer import Answerer, answer_question
from .incident import load_record, normalized, photo_contradicts, submit_attacked
from .record import save_run
from .workflow import Workflow


def run_turn(raw: dict, *, workflow: Workflow, answerer: Answerer, cracked: dict[str, str] | None = None,
             usage: SessionUsage | None = None, analyst_id: UUID | str | None = None,
             metered: list[MeteredCall] | None = None) -> TurnRun:
    """ every command goes through here, and every turn leaves a run record, refused or not

        usage is the session's from its last turn, so the cost ceiling accumulates; the TurnRun carries it on.
        The budget itself is the turn meter's (harness/metering), which the caller wraps the turn in.
        analyst_id is the verified analyst from the session, never a request field; a turn that escalates needs it,
        because the review queue row records who submitted the dossier.
        metered is the turn meter's list of priced calls, still filling as the turn runs; the run record keeps it.
    """

    correlation_id = uuid4()
    cid = str(correlation_id)
    stored = load_record(raw.get("incident_id"))
    incident = normalized(stored)
    turn = check_turn(raw, incident=incident, cracked=cracked or {}, correlation_id=cid)
    request = turn["request"]
    command = request["command"] if request else str(raw.get("command") or "invalid")
    run = {"route": turn["route"], "refusal": turn["refusal"], "problems": turn["problems"], "events": list(turn["events"])}
    invocations = list(turn["rule_invocations"])
    # only what a stage actually produced; an absent signal is recorded as unevaluated, never as clear
    # an attack withheld this turn, or when the packet was submitted: the submitted facts carry it (section 10)
    signals: dict = {"prompt_attack_detected": turn["prompt_attack_detected"] or submit_attacked(stored),
                     # the photo verdicts submit stored; a contradicting photo is an escalation trigger (section 10)
                     "photo_contradicts": photo_contradicts(stored)}
    workers: list[str] | None = None
    result = None
    
    if incident:
        key = UUID(incident.incident_id)
        usage = start_turn(usage, cid) if usage else SessionUsage(session_id=str(key), incident_id=key, turn=TurnUsage(turn_id=cid))

    recorded: list[RuleInvocation] = []
    if run["refusal"] is None and run["route"] == "answer_from_record":
        # a follow-up on the incident's analysis reuses the decisions it recorded; with none to reuse, it analyzes
        recorded = recorded_decisions(incident) if incident else []
        if not recorded:
            run["route"] = "route_to_analyst" if run["problems"] else "run_workflow"

    if run["refusal"] is None and run["route"] == "run_workflow" and incident:
        result = workflow(incident, request.get("question"), cid)
        invocations += result.rule_invocations
        workers = result.workers_dispatched
        # a leg stage 4 still blocks when the caps run out is refused, not shown; blocked keeps what was wrong with it
        dossier = {worker: leg for worker, leg in result.dossier.items() if worker not in result.blocked}
        run |= {"dossier": dossier, "blocked": result.blocked, "unavailable": result.unavailable, "events": run["events"] + result.events}
        signals |= {"reviewer_approved": result.reviewer_approved, "reviewer_iterations": result.reviewer_iterations,
                    "citations_supported": result.citations_supported, "retrieval_scores": result.retrieval_scores}

    elif run["refusal"] is None and run["route"] in ("answer_from_retrieval", "answer_from_record"):
        follow_up = run["route"] == "answer_from_record"
        answered = answer_question(request["question"], answerer, incident=incident, rule_invocations=invocations + recorded,
                                   correlation_id=cid, about_incident=follow_up)
        invocations, events = answered.pop("rule_invocations"), answered.pop("events")
        run |= {**answered, "events": run["events"] + events}

    # the harness's own rule run decides whether the dossier stands; a turn with no dossier and no attack has nothing to escalate
    results, decision = None, None
    if incident and (run["route"] in ("run_workflow", "route_to_analyst") or signals["prompt_attack_detected"]):
        results = evaluate_incident(incident)
        # the readiness gate already ran and recorded R5 this turn; every other rule's invocation is recorded here
        gated = {invocation.decision.rule_id for invocation in turn["rule_invocations"]}
        invocations += [invocation for invocation in results.invocations if invocation.decision.rule_id not in gated]
        policy = EscalationPolicy(retrieval_score_threshold=settings.retrieval_score_threshold)
        decision = evaluate_escalation(incident, results, signals=EscalationSignals(**signals), policy=policy)

    # the one write for the turn: the run record, and the queue row with its snapshot when escalation fired
    snapshot = None
    if decision and decision.requires_review and analyst_id is not None:
        snapshot = ReviewSnapshot.of(analyst_id, run.get("dossier"))
    run_id = save_run(correlation_id, command, incident, results=results, decision=decision,
                      rule_invocations=invocations, workers=workers, workflow=result, review_snapshot=snapshot,
                      dossier=run.get("dossier"), metered=metered)
    
    return TurnRun(run_id=run_id, correlation_id=correlation_id, command=command, escalation=decision, usage=usage, **run)


def recorded_decisions(incident: NormalizedIncident) -> list[RuleInvocation]:
    """ the rule invocations the incident's latest analyze turn recorded, for a follow-up to reuse """

    record = RunRepository().latest(UUID(incident.incident_id), ("analyze",))
    items = ((record or {}).get("rule_invocations") or {}).get("items") or []
    return [RuleInvocation.model_validate(item) for item in items]
