""" what the guardrail stages share: the event sink, refusals, and the output checks both stage 4 guards run """

import logging
import re

from ...retrieval.grounding import ESCALATION
from ...schemas.run_records import RuleInvocation
from ...types.guardrails import GuardrailEvent, GuardrailRefusal, Refusal, Remedy, Stage

log = logging.getLogger(__name__)

DISCLOSURE = ("AI-generated; verify before relying on it. FieldSight describes what the regulation says, "
              "and the analyst makes the determination. All incident data is synthetic.")

CITATION = re.compile(r"\[(\d+)\]")

# a legal conclusion on the firm's behalf; the system describes, the analyst determines
DETERMINATION = re.compile(
    r"\byou (?:must|need to|are required to|have to|should) (?:record|report|log|file|notify)\b"
    r"|\b(?:must|shall|should) be (?:recorded|reported|logged)\b"
    r"|\b(?:we|i|fieldsight) (?:have )?(?:determined|concluded|conclude|determine)\b"
    r"|\b(?:this|the) (?:case|incident|injury|illness|event) (?:is|was) (?:not )?(?:recordable|reportable)\b",
    re.IGNORECASE)


def emit(events: list[GuardrailEvent], correlation_id: str, stage: Stage, failure: str, remedy: Remedy, trigger: str) -> None:
    """ the event's sink: a structured log line now, and the list the run record takes """

    event = GuardrailEvent(correlation_id=correlation_id, stage=stage, failure=failure, remedy=remedy, trigger=trigger)
    log.warning("guardrail event", extra=dict(event))
    events.append(event)


def refuse(reason: GuardrailRefusal, message: str) -> Refusal:
    return Refusal(reason=reason, message=message, escalation=ESCALATION)


def claims(text: str) -> list[str]:
    """ the text's sentences, each a claim that must carry a citation """

    return [s for s in re.split(r"(?<=[.!?])\s+", text.replace(DISCLOSURE, "").strip()) if s]


def citation_problems(text: str, chunk_ids: list[str], retrieved: set[str]) -> tuple[list[str], list[str]]:
    """ (uncited claims, citations that don't resolve to a chunk retrieved this turn) """

    uncited = [claim for claim in claims(text) if not CITATION.search(claim)]
    unresolved = [f"[{n}]" for n in sorted({int(n) for n in CITATION.findall(text)})
                  if not 1 <= n <= len(chunk_ids) or chunk_ids[n - 1] not in retrieved]
    return uncited, unresolved


def latest(invocations: list[RuleInvocation]) -> dict[str, dict]:
    """ the latest decision per rule this turn """

    return {i.decision.rule_id: i.decision.model_dump(mode="json") for i in invocations}
