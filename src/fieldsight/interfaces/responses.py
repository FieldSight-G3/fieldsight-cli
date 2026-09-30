""" what the harness returns, shaped into what the analyst reads; every function returns text and decides nothing """

from typing import Any

from ..harness.escalation.review import PendingReview, ReviewDecision
from ..types.artifacts import SubmitResult
from ..types.guardrails import Refusal
from ..types.run import TurnRun


def refusal(refused: Refusal) -> str:
    """ a refusal is an answer: the reason, what to tell the analyst, and where to escalate """

    return f"Refused ({refused['reason']}): {refused['message']}\nEscalation: {refused['escalation']}"


def denied(code: str, message: str) -> str:
    return f"Refused ({code}): {message}"


def citation(number: int, chunk_id: str, hit: dict) -> str:
    return f"[{number}] {hit.get('doc_id')} {hit.get('section_path')}, {hit.get('title')} ({chunk_id})"


def leg_lines(worker: str, leg: dict) -> list[str]:
    """ one dossier leg: its proposal, the rule and inputs behind each computed outcome, and where each citation resolves """

    proposal = leg.get("proposal")
    if proposal is None:
        return [f"{worker}: no proposal"]
    lines = [f"{worker}: {proposal['outcome']}", f"  {proposal['rationale']}"]
    for decision in leg.get("decisions", {}).values():
        inputs = ", ".join(f"{name}={value}" for name, value in decision["inputs"].items())
        lines.append(f"  {decision['rule_id']} -> {decision['outcome']} (inputs: {inputs})")
    lines += [f"  {citation(number, chunk_id, leg.get('cited', {}).get(chunk_id, {}))}"
              for number, chunk_id in enumerate(proposal["chunk_ids"], 1)]
    return lines


def dossier_lines(dossier: dict) -> list[str]:
    return [line for worker, leg in dossier.items() for line in leg_lines(worker, leg)]


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
    lines += [f"Photo not corroborated yet: {photo}" for photo in result["photos"]]
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
