"""The fieldsight command line: each command maps its arguments to one harness call and prints the shaped result."""

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from ..errors import FieldSightError, ToolDenied
from ..harness.guardrails.common import DISCLOSURE
from ..harness.run import wiring
from ..logging_context import configure_logging
from ..security.identity import current_analyst
from . import remote, requests, responses


def cmd_submit(args: argparse.Namespace, analyst_id: UUID) -> str:
    return responses.submitted(wiring.submit(Path(args.folder), analyst_id=analyst_id))


def run_turn(request: dict, analyst_id: UUID | None) -> str:
    """ a turn here, or on the deployed Runtime when FIELDSIGHT_RUNTIME_ID is set """

    if runtime := remote.runtime_id():
        return responses.turn(remote.turn(request, runtime))
    return responses.turn(wiring.turn(request, analyst_id=analyst_id))


def cmd_analyze(args: argparse.Namespace, analyst_id: UUID | None) -> str:
    return run_turn(requests.turn_request("analyze", args.incident_id), analyst_id)


def cmd_dossier(args: argparse.Namespace, analyst_id: UUID) -> str:
    run = wiring.latest_run(args.incident_id, analyst_id=analyst_id, commands=("analyze",))
    return responses.dossier(run, args.incident_id)


def cmd_ask(args: argparse.Namespace, analyst_id: UUID | None) -> str:
    return run_turn(requests.turn_request("ask", args.incident_id, args.question), analyst_id)


def cmd_sources(args: argparse.Namespace, analyst_id: UUID) -> str:
    run = wiring.latest_run(args.incident_id, analyst_id=analyst_id, commands=("analyze",))
    return responses.sources(run, args.incident_id, args.ref)


def cmd_trace(args: argparse.Namespace, analyst_id: UUID) -> str:
    return responses.trace(wiring.latest_run(args.incident_id, analyst_id=analyst_id), args.incident_id)


def cmd_queue(args: argparse.Namespace, analyst_id: UUID) -> str:
    return responses.queue(wiring.review_queue(analyst_id))


def cmd_review(args: argparse.Namespace, analyst_id: UUID) -> str:
    """ no action shows the decision card; an action records the decision as this analyst """

    if args.action is None:
        return responses.review_card(wiring.pending_review(args.incident_id, analyst_id=analyst_id), args.incident_id)
    request = requests.review_request(args.action, args.reason, args.narrative, args.note, args.repoint)
    return responses.decision(wiring.record_review(args.incident_id, request, analyst_id=analyst_id))


# the turns the deployed Runtime serves; the rest read and write the database this process is configured for
REMOTE = {"analyze", "ask"}

COMMANDS: dict[str, Callable[[argparse.Namespace, UUID | None], str]] = {
    "submit": cmd_submit,
    "analyze": cmd_analyze,
    "dossier": cmd_dossier,
    "ask": cmd_ask,
    "sources": cmd_sources,
    "trace": cmd_trace,
    "queue": cmd_queue,
    "review": cmd_review,
}


def parser() -> argparse.ArgumentParser:
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
    
    return parser


def main() -> None:
    args = parser().parse_args()
    # logs go to a file, so the terminal shows only the result; FIELDSIGHT_CLI_LOG moves it
    configure_logging(path=Path(os.environ.get("FIELDSIGHT_CLI_LOG") or Path.home() / ".fieldsight" / "cli.log"))
    try:
        # on the Runtime the analyst is resolved there, from the caller proof, never here
        analyst = None if remote.runtime_id() and args.command in REMOTE else current_analyst()
        print(COMMANDS[args.command](args, analyst))
    except (ToolDenied, remote.RemoteDenied) as denied:
        print(responses.denied(denied.code, str(denied)))
    except (FieldSightError, ValueError) as error:
        # a review conflict, an unentitled reviewer, or an edit that changes a determination: an answer, not a crash
        print(f"Refused: {error}")
    print(f"\n{DISCLOSURE}")


if __name__ == "__main__":
    main()
