"""CLI command implementations: load config, build services, run, render."""

import argparse
from pathlib import Path
from uuid import UUID

from ..errors import FieldSightError, ToolDenied
from ..harness.escalation.review import (
    CitationRepoint,
    ReviewEdit,
    ReviewRequest,
    document_for_chunk,
    submit_review,
)
from ..harness.guardrails.common import DISCLOSURE
from ..harness.run.wiring import submit, turn
from ..logging_context import configure_logging
from ..repository import ReviewQueueRepository
from ..security.identity import current_analyst
from ..types.guardrails import Refusal
from ..types.run import TurnRun


def render_refusal(refusal: Refusal) -> None:
    print(f"Refused ({refusal['reason']}): {refusal['message']}\nEscalation: {refusal['escalation']}")


def render_leg(worker: str, leg: dict) -> None:
    """ one dossier leg: its proposal, the rule and inputs behind each computed outcome, and where each citation resolves """

    proposal = leg.get("proposal")
    if proposal is None:
        print(f"{worker}: no proposal")
        return
    print(f"{worker}: {proposal['outcome']}\n  {proposal['rationale']}")
    for decision in leg.get("decisions", {}).values():
        inputs = ", ".join(f"{name}={value}" for name, value in decision["inputs"].items())
        print(f"  {decision['rule_id']} -> {decision['outcome']} (inputs: {inputs})")
    for number, chunk_id in enumerate(proposal["chunk_ids"], 1):
        hit = leg.get("cited", {}).get(chunk_id, {})
        print(f"  [{number}] {hit.get('doc_id')} {hit.get('section_path')}, {hit.get('title')} ({chunk_id})")


def render_turn(run: TurnRun) -> None:
    """ an analyze or ask turn: its refusal or answer, the dossier legs, what was withheld, and whether it escalated """

    if run.refusal:
        render_refusal(run.refusal)
    if run.problems:
        print(f"Routed to the analyst: {'; '.join(run.problems)}")
    if run.answer:
        print(run.answer)
    for number, source in enumerate(run.sources, 1):
        print(f"[{number}] {source.doc_id} {source.section_path}, {source.title} ({source.chunk_id})")
    for worker, leg in (run.dossier or {}).items():
        render_leg(worker, leg)
    for worker, problems in run.blocked.items():
        print(f"{worker}: withheld ({'; '.join(problems)})")
    if run.escalation and run.escalation.requires_review:
        print(f"Escalated to the review queue: {', '.join(run.escalation.fired)}")
    elif run.escalation:
        print("No escalation trigger fired")


def cmd_submit(analyst_id: UUID, folder: str) -> None:
    result = submit(Path(folder), analyst_id=analyst_id)
    if result["refusal"]:
        render_refusal(result["refusal"])
        return
    report = result["report"]
    print(f"Incident {result['incident_id']} ({result['establishment']})")
    print(f"Artifacts processed: {report['artifacts_processed']}, fields extracted: {report['fields_extracted']}")
    print(f"Fields below the confidence floor: {', '.join(report['fields_below_floor']) or 'none'}")
    for failure in report["failures"]:
        print(f"Skipped {failure['artifact']}: {failure['reason']}")
    for source in result["withheld"]:
        print(f"Withheld by the Prompt Attacks filter: {source}")
    for photo in result["photos"]:
        print(f"Photo not corroborated yet: {photo}")


def cmd_analyze(analyst_id: UUID, incident_id: str) -> None:
    render_turn(turn({"command": "analyze", "incident_id": incident_id}, analyst_id=analyst_id))


def cmd_dossier():
    pass


def cmd_ask(
        analyst_id: UUID, 
        incident_id: str, 
        question: str
        ) -> None:
    render_turn(turn({"command": "ask", "incident_id": incident_id, "question": question}, analyst_id=analyst_id))


def cmd_sources():
    pass


def cmd_trace():
    pass


def cmd_queue(analyst_id: UUID) -> None:
    for item in ReviewQueueRepository().list_pending(reviewer_id=analyst_id):
        print(f"{item.incident_id}  {', '.join(item.triggers.get('fired', []))}")


def cmd_review(
        analyst_id: UUID, 
        incident_id: str, 
        action: str | None, 
        reason: str | None,
        narrative: str | None,
        note: str | None,
        repoints: list[str] | None
        ) -> None:
    """ no action shows the decision card; an action records the decision as this analyst """

    queue = ReviewQueueRepository()
    pending = queue.pending_for_incident(UUID(incident_id))
    if pending is None:
        print(f"No pending review for {incident_id}")
        return
    if action is None:
        for worker, leg in pending.original_payload.items():
            render_leg(worker, leg)
        print("Citations a reviewer may repoint to another chunk of the same document:")
        for citation_id, citation in pending.original_citations.items():
            print(f"  {citation_id}: {citation.document_id}")
        print("Decide with --action approve | edit_then_approve (--narrative, --note, --repoint CITATION=CHUNK) | reject (--reason)")
        return
    # CITATION=CHUNK pairs; review.decide_review checks the new chunk is in the same document
    citation_repoints = [CitationRepoint(citation_id=citation, replacement_chunk_id=chunk)
                         for citation, _, chunk in (pair.partition("=") for pair in repoints or [])]
    edit = (ReviewEdit(narrative=narrative, note=note, citation_repoints=citation_repoints)
            if action == "edit_then_approve" else None)
    decision = submit_review(ReviewRequest(action=action, edit=edit, reason=reason), queue_id=pending.queue_id,
                             verified_reviewer_id=analyst_id, store=queue, source_for_chunk=document_for_chunk)
    print(f"Recorded {decision.action} ({decision.status}) by {decision.reviewer_id} at {decision.decided_at.isoformat()}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="fieldsight")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("submit").add_argument("folder")
    commands.add_parser("analyze").add_argument("incident_id")
    commands.add_parser("dossier").add_argument("incident_id")
    ask = commands.add_parser("ask")
    ask.add_argument("incident_id")
    ask.add_argument("question")
    sources = commands.add_parser("sources")
    sources.add_argument("incident_id")
    sources.add_argument("--ref", type=int)
    commands.add_parser("trace").add_argument("incident_id")
    commands.add_parser("queue")
    review = commands.add_parser("review")
    review.add_argument("incident_id")
    review.add_argument("--action", choices=["approve", "edit_then_approve", "reject"])
    review.add_argument("--reason")
    review.add_argument("--narrative")
    review.add_argument("--note")
    review.add_argument("--repoint", action="append", metavar="CITATION=CHUNK")
    args = parser.parse_args()

    configure_logging()
    try:
        analyst_id = current_analyst()
        if args.command == "submit":
            cmd_submit(analyst_id, args.folder)
        elif args.command == "analyze":
            cmd_analyze(analyst_id, args.incident_id)
        elif args.command == "dossier":
            cmd_dossier()
        elif args.command == "ask":
            cmd_ask(analyst_id, args.incident_id, args.question)
        elif args.command == "sources":
            cmd_sources()
        elif args.command == "trace":
            cmd_trace()
        elif args.command == "queue":
            cmd_queue(analyst_id)
        elif args.command == "review":
            cmd_review(analyst_id, args.incident_id, args.action, args.reason, args.narrative, args.note, args.repoint)
    except ToolDenied as denied:
        print(f"Refused ({denied.code}): {denied}")
    except (FieldSightError, ValueError) as error:
        # a review conflict, an unentitled reviewer, or an edit that changes a determination: an answer, not a crash
        print(f"Refused: {error}")
    print(f"\n{DISCLOSURE}")


if __name__ == "__main__":
    main()
