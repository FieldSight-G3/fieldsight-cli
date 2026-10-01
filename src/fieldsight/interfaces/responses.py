""" what the harness returns, shaped into what the analyst reads; every function returns text and decides nothing """

import re
from decimal import Decimal
from typing import Any

from ..harness.escalation.review import PendingReview, ReviewDecision
from ..harness.guardrails.common import CITATION
from ..types.artifacts import SubmitResult
from ..types.guardrails import Refusal
from ..types.run import TurnRun


def refusal(refused: Refusal) -> str:
    """ a refusal is an answer: the reason, what to tell the analyst, and where to escalate """

    return f"Refused ({refused['reason']}): {refused['message']}\nEscalation: {refused['escalation']}"


def denied(code: str, message: str) -> str:
    return f"Refused ({code}): {message}"


def references(dossier: dict) -> dict[str, dict]:
    """ every chunk the dossier cites, in the order it's shown, so [n] means the same chunk everywhere it's printed """

    refs: dict[str, dict] = {}
    for leg in dossier.values():
        for chunk_id in (leg.get("proposal") or {}).get("chunk_ids", []):
            refs.setdefault(chunk_id, leg.get("cited", {}).get(chunk_id, {}))
    return refs


def citation(number: int, chunk_id: str, hit: dict) -> str:
    return f"[{number}] {hit.get('doc_id')} {hit.get('section_path')}, {hit.get('title')} ({chunk_id})"


def leg_lines(worker: str, leg: dict, numbers: dict[str, int]) -> list[str]:
    """ one dossier leg: its proposal, the rule and inputs behind each computed outcome, and where each citation resolves """

    proposal = leg.get("proposal")
    if proposal is None:
        return [f"{worker}: no proposal"]
    chunk_ids = proposal["chunk_ids"]

    def renumber(match: re.Match) -> str:
        # the rationale's [n] is its own leg's nth chunk; shown with the dossier-wide number
        index = int(match[1]) - 1
        return f"[{numbers[chunk_ids[index]]}]" if 0 <= index < len(chunk_ids) else match[0]

    lines = [f"{worker}: {proposal['outcome']}", f"  {CITATION.sub(renumber, proposal['rationale'])}"]
    for decision in leg.get("decisions", {}).values():
        inputs = ", ".join(f"{name}={value}" for name, value in decision["inputs"].items())
        lines.append(f"  {decision['rule_id']} -> {decision['outcome']} (inputs: {inputs})")
    lines += [f"  {citation(numbers[chunk_id], chunk_id, leg.get('cited', {}).get(chunk_id, {}))}" for chunk_id in chunk_ids]
    return lines


def dossier_lines(dossier: dict) -> list[str]:
    numbers = {chunk_id: number for number, chunk_id in enumerate(references(dossier), 1)}
    return [line for worker, leg in dossier.items() for line in leg_lines(worker, leg, numbers)]


def turn(run: TurnRun) -> str:
    """ an analyze or ask turn: its refusal or answer, the dossier legs, what was withheld, and whether it escalated """

    lines = [refusal(run.refusal)] if run.refusal else []
    if run.problems:
        lines.append(f"Routed to the analyst: {'; '.join(run.problems)}")
    if run.answer:
        lines.append(run.answer)
    lines += [f"[{number}] {source.doc_id} {source.section_path}, {source.title} ({source.chunk_id})"
              for number, source in enumerate(run.sources, 1)]
    lines += dossier_lines(run.dossier or {})
    lines += [f"{worker}: withheld ({'; '.join(problems)})" for worker, problems in run.blocked.items()]
    lines += [f"Unavailable this turn: {tool} ({why})" for tool, why in run.unavailable.items()]
    if run.escalation and run.escalation.requires_review:
        lines.append(f"Escalated to the review queue: {', '.join(run.escalation.fired)}")
    elif run.escalation:
        lines.append("No escalation trigger fired")
    return "\n".join(lines)


def submitted(result: SubmitResult) -> str:
    """ the new incident and its ingestion report, or the refusal that stopped it """

    if result["refusal"]:
        return refusal(result["refusal"])
    report = result["report"]
    lines = [f"Incident {result['incident_id']} ({result['establishment']})",
             f"Artifacts processed: {report['artifacts_processed']}, fields extracted: {report['fields_extracted']}",
             f"Fields below the confidence floor: {', '.join(report['fields_below_floor']) or 'none'}"]
    lines += [f"Skipped {failure['artifact']}: {failure['reason']}" for failure in report["failures"]]
    lines += [f"Withheld by the Prompt Attacks filter: {source}" for source in result["withheld"]]
    lines += [f"Photo {photo['artifact']}: {photo['verdict']}. {photo['observation']} ({photo['reason']})"
              for photo in result["photos"]]
    return "\n".join(lines)


def dossier(run: dict[str, Any] | None, incident_id: str) -> str:
    """ the dossier the latest analyze showed, with dossier-wide citation numbers and the triggers it escalated on """

    if run is None or run.get("dossier") is None:
        return f"No analyzed dossier for {incident_id}; run fieldsight analyze first"
    fired = (run["escalation_triggers"] or {}).get("fired", [])
    return "\n".join([f"Dossier from analyze run {run['run_id']} at {run['created_at'].isoformat()}",
                      *dossier_lines(run["dossier"]),
                      f"Escalation: {', '.join(fired) or 'no trigger fired'}"])


def sources(run: dict[str, Any] | None, incident_id: str, ref: int | None) -> str:
    """ the chunk behind dossier citation [ref], or every cited chunk: document, section, title and the text itself """

    if run is None or run.get("dossier") is None:
        return f"No analyzed dossier for {incident_id}; run fieldsight analyze first"
    numbered = list(enumerate(references(run["dossier"]).items(), 1))
    if ref is not None:
        numbered = [entry for entry in numbered if entry[0] == ref]
        if not numbered:
            return f"No reference [{ref}] in the dossier for {incident_id}"
    return "\n\n".join(f"{citation(number, chunk_id, hit)}\n{hit.get('text', '')}" for number, (chunk_id, hit) in numbered)


def trace(run: dict[str, Any] | None, incident_id: str) -> str:
    """ the latest turn's run record: the plan and re-dispatches, the tool loops, verdicts, rules and tokens per agent """

    if run is None:
        return f"No analyze or ask run for {incident_id}"
    lines = [f"{run['command']} run {run['run_id']} at {run['created_at'].isoformat()} (correlation {run['correlation_id']})"]

    for number, plan in enumerate((run["workers_dispatched"] or {}).get("plans", []), 1):
        lines.append(f"Plan {number} ({plan['trigger']}):")
        lines += [f"  {dispatch['worker']}: {dispatch['reason']}" for dispatch in plan["dispatches"]]
        lines += [f"  {dispatch['worker']} dropped: its energized-equipment quote isn't in the narrative"
                  for dispatch in plan.get("ungrounded", [])]

    lines.append("Tool calls:")
    for call in (run["tool_invocations"] or {}).get("items", []):
        outcome = "requested, never ran" if call["outcome"] is None else call["outcome"][:160]
        lines.append(f"  {call['agent']} {call['tool']}({call['args']}) -> {outcome}")

    for number, verdict in enumerate((run.get("reviewer_verdicts") or {}).get("items", []), 1):
        if verdict is None:
            lines.append(f"Review {number}: no verdict")
            continue
        lines.append(f"Review {number}: {'approved' if verdict['approved'] else 'rejected'}")
        lines += [f"  {rejection['worker']}: {rejection['problem']} (narrowed goal: {rejection['narrowed_goal']})"
                  for rejection in verdict.get("rejections", [])]

    lines.append("Rules:")
    for invocation in (run["rule_invocations"] or {}).get("items", []):
        decision = invocation["decision"]
        inputs = ", ".join(f"{name}={value}" for name, value in decision["inputs"].items())
        lines.append(f"  {decision['rule_id']} -> {decision['outcome']} (inputs: {inputs})")

    lines.append("Model calls per agent:")
    totals: dict[str, tuple[int, int, Decimal]] = {}
    for call in (run["model_calls"] or {}).get("items", []):
        tokens_in, tokens_out, cost = totals.get(call["agent"], (0, 0, Decimal(0)))
        totals[call["agent"]] = (tokens_in + call["input_tokens"], tokens_out + call["output_tokens"], cost + Decimal(call["cost_usd"]))
    lines += [f"  {agent}: {tokens_in} in, {tokens_out} out, ${cost}" for agent, (tokens_in, tokens_out, cost) in totals.items()]

    fired = (run["escalation_triggers"] or {}).get("fired", [])
    lines.append(f"Escalation: {', '.join(fired) or 'no trigger fired'}")
    return "\n".join(lines)


def queue(items: list[Any]) -> str:
    """ each pending incident and the triggers it escalated on """

    if not items:
        return "No pending reviews"
    return "\n".join(f"{item.incident_id}  {', '.join(item.triggers.get('fired', []))}" for item in items)


def review_card(pending: PendingReview | None, incident_id: str) -> str:
    """ the decision card: the frozen dossier, the citations a reviewer may repoint, and the three decisions """

    if pending is None:
        return f"No pending review for {incident_id}"
    lines = dossier_lines(pending.original_payload)
    lines.append("Citations a reviewer may repoint to another chunk of the same document:")
    lines += [f"  {citation_id}: {reference.document_id}" for citation_id, reference in pending.original_citations.items()]
    lines.append("Decide with --action approve | edit_then_approve (--narrative, --note, --repoint CITATION=CHUNK) | reject (--reason)")
    return "\n".join(lines)


def decision(decided: ReviewDecision) -> str:
    return f"Recorded {decided.action} ({decided.status}) by {decided.reviewer_id} at {decided.decided_at.isoformat()}"
