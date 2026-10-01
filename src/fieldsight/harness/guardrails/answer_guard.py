""" stage 4 on a generated answer: citations, attributed thresholds, descriptive language, PII, the disclosure """

import re
from collections.abc import Callable

from ...ingest.artifacts.redact import scrub_text
from ...rules.engine import evaluate_incident
from ...schemas.incidents import NormalizedIncident
from ...schemas.retrieval import DraftAnswer
from ...schemas.run_records import RuleInvocation
from ...types.guardrails import GuardrailEvent
from .common import DETERMINATION, DISCLOSURE, citation_problems, emit, latest, refuse

MAX_REGENERATIONS = 2

# threshold outcomes only the rules engine may produce, by the rule that produces them
THRESHOLDS = {
    "R1": re.compile(r"\b(?:is|was|are|be) (?:not )?recordable\b", re.IGNORECASE),
    "R2": re.compile(r"\b(?:is|was|are|be) (?:not )?reportable\b|\breporting deadline\b", re.IGNORECASE),
    "R3": re.compile(r"\bbeyond first aid\b|\b(?:is|was) (?:only )?first aid\b", re.IGNORECASE),
    "R4": re.compile(r"\bcolumn [GHIJ]\b|\bday count\b", re.IGNORECASE),
}


def guard_answer(generate: Callable[[list[str]], DraftAnswer], *,
                 incident: NormalizedIncident | Callable[[], NormalizedIncident | None] | None,
                 retrieved: set[str], rule_invocations: list[RuleInvocation], names: set[str],
                 correlation_id: str) -> dict:
    """ generate(objections) drafts the answer again with the objections attached

        returns the text safe to show (or a refusal), citations_supported for EscalationSignals,
        this turn's rule invocations including any the guard ran, and the events

        incident is the facts the answer's thresholds are attributed to; a callable is resolved only when a threshold
        needs them, so a turn that states none never pays for reading them
    """

    facts: list[NormalizedIncident | None] = []

    def subject() -> NormalizedIncident | None:
        if not facts:
            facts.append(incident() if callable(incident) else incident)
        return facts[0]

    def result(text: str | None, refusal: dict | None) -> dict:
        return {"text": text, "refusal": refusal, "citations_supported": citations_supported,
                "rule_invocations": invocations, "events": events}

    events: list[GuardrailEvent] = []
    invocations = list(rule_invocations)
    citations_supported = True
    retried_determination = False

    draft = generate([])
    for attempt in range(MAX_REGENERATIONS + 1):
        objections: list[str] = []
        uncited, unresolved = citation_problems(draft.answer, draft.chunk_ids, retrieved)
        citations_supported &= not unresolved
        objections += [f'Cite this claim or remove it: "{claim}"' for claim in uncited]
        objections += [f"{ref} doesn't cite a chunk retrieved this turn" for ref in unresolved]

        # a threshold outcome with no rules-engine invocation: run the rules (the harness path), inject, regenerate
        unattributed = [rule for rule, pattern in THRESHOLDS.items() if pattern.search(draft.answer) and rule not in latest(invocations)]
        if unattributed and subject():
            invocations += evaluate_incident(subject()).invocations
            emit(events, correlation_id, "output", "unattributed_threshold", "rule_run", ",".join(unattributed))
        decisions = latest(invocations)
        objections += [f"{rule} returned {decisions[rule]['outcome']}; state only that, attributed to {rule}" if rule in decisions
                       else f"No rule decided {rule}'s outcome this turn; remove it" for rule in unattributed]

        # determination-shaped language: regenerate once, then refuse and log a gate miss
        determination = DETERMINATION.search(draft.answer)
        if determination and retried_determination:
            emit(events, correlation_id, "output", "determination_language", "gate_miss", determination.group())
            return result(None, refuse("output_blocked", "The answer kept stating a determination."))
        if determination:
            retried_determination = True
            objections.append(f'Describe what the regulation says instead of concluding: "{determination.group()}"')

        if not objections:
            break
        if attempt == MAX_REGENERATIONS:
            emit(events, correlation_id, "output", "unfixed_output", "refused", "; ".join(objections)[:200])
            return result(None, refuse("output_blocked", "The answer couldn't be grounded and attributed."))
        for objection in objections:
            emit(events, correlation_id, "output", "objection", "regenerated", objection[:200])
        draft = generate(objections)

    # PII: redact deterministically, never regenerate
    text, spans = scrub_text(draft.answer, names, "answer")
    for span in spans:
        emit(events, correlation_id, "output", "pii", "redacted", span["kind"])
    # missing disclosure: append deterministically
    if DISCLOSURE not in text:
        text = f"{text}\n\n{DISCLOSURE}"
        emit(events, correlation_id, "output", "missing_disclosure", "appended", "disclosure")
    return result(text, None)
