""" the live tier (§14): each golden case's turns through the real harness, checked against its run records

    Mechanical checks read the TurnRun and the stored run record: outcome, refusal reason, forbidden phrases, sources,
    rule outcomes, workers dispatched, escalation triggers, and rule-invocation reuse across turns. Expected statements
    and groundedness go to the judge model. An expectation key this runner doesn't check is listed as unchecked, so
    the report never claims more coverage than it has.
"""

import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ..checkpoint import thread_id
from ..harness.guardrails.common import DISCLOSURE
from ..harness.run import wiring
from ..repository import IncidentRepository, RunRepository, SessionRepository
from ..types.run import TurnRun
from . import judge
from .deterministic import TRIGGERS
from .golden import turns

ROOT = Path(__file__).resolve().parents[3]
# every turn is asked about an incident; a general question (incident_id: null) is asked under this seeded one,
# which Alice is granted and which has the same id in every database the seed has run on
CONTEXT_INCIDENT = "60f2ee61-8c21-5e24-a7ed-65711dbc9a25"

# the golden set's names for what the harness calls them, beyond the paired triggers
TRIGGER_NAMES = TRIGGERS | {"photo_contradicts_narrative": "photo_contradiction", "reviewer_needed_more_than_one_iteration":
                            "reviewer", "citation_failed": "citation", "below_similarity_threshold": "retrieval",
                            "fatality": "fatality"}
# the golden set's refusal reasons, as the harness reports them (a retrieval refusal, or a guardrail refusal)
REFUSALS = {"below_similarity_threshold": "below_threshold", "retrieval_unavailable": "retrieval_unavailable",
            "action_not_permitted": "action_requested"}
REFUSING = {"refusal"}
ANSWERING = {"answer", "answer_without_determination"}
CHECKED = {"outcome", "refusal", "must_not_include", "answer_must_include", "sources", "rule_outcomes",
           "workers_dispatched", "workers_not_dispatched", "escalation_triggers_fired", "escalation_triggers_not_fired",
           "escalated_to_review_queue", "rules_engine_invocation_required", "reuses_rule_invocation_from_turn",
           "reused_rule_id", "must_not_refuse", "writes_performed", "review_queue_row_unchanged"}


@dataclass
class TurnResult:
    command: str
    seconds: float
    cost_usd: float
    refused: bool | None                                   # None for a turn with no answer to refuse (analyze, submit)
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)
    judged: list[dict] = field(default_factory=list)       # statement verdicts
    grounded: list[dict] = field(default_factory=list)     # groundedness verdicts, one per cited claim
    error: str | None = None
    route: str | None = None                               # where the readiness gate sent the turn
    text: str = ""                                         # what the analyst read: the answer and the dossier rationales
    sources: list[str] = field(default_factory=list)       # "doc_id section_path" of every cited chunk


@dataclass
class LiveResult:
    case_id: str
    category: str
    variant: str | None
    turns: list[TurnResult] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(not t.failed and t.error is None for t in self.turns)


class Incidents:
    """ the golden set's incident ids as rows in this database: each packet submitted once per run, and each case
        given its own copy of its packet's incident, so no two cases share threads, a session or a queue row

        cache, when given, keeps packet -> submitted incident across runs (--reuse-packets): a packet whose files
        haven't changed, and whose incident is still in this database, isn't submitted again.
    """

    def __init__(self, analyst_id: UUID, cache: Path | None = None) -> None:
        self.analyst_id = analyst_id
        self.submitted: dict[str, str] = {}
        self.cache = cache
        self.cached: dict[str, dict] = json.loads(cache.read_text(encoding="utf-8")) if cache and cache.exists() else {}

    def packet(self, case: dict[str, Any]) -> Path | None:
        setup = case.get("setup") or {}
        if setup.get("base_packet"):
            return ROOT / setup["base_packet"]
        if case.get("fixture"):
            return ROOT / case["fixture"]
        incident = case.get("incident_id") or ""
        if incident.startswith("INC-2026-"):
            return ROOT / "packets" / f"inc-{incident.rsplit('-', 1)[1]}"
        return None

    def packets(self, case: dict[str, Any]) -> list[Path]:
        """ every packet the case submits: its own incident's, and any a submit turn sends """

        own = self.packet(case)
        return ([own] if own else []) + [ROOT / turn["path"] for turn in turns(case) if turn.get("command") == "submit"]

    def submit(self, folder: Path) -> str:
        key = str(folder.resolve())
        if key in self.submitted:
            return self.submitted[key]
        signature = _signature(folder)
        cached = self.cached.get(key)
        if cached and cached["signature"] == signature and IncidentRepository().get(UUID(cached["incident_id"])):
            self.submitted[key] = cached["incident_id"]
            return cached["incident_id"]
        result = wiring.submit(folder, analyst_id=self.analyst_id)
        if result["refusal"]:
            raise RuntimeError(f"submit of {folder.name} was refused: {result['refusal']}")
        self.submitted[key] = result["incident_id"]
        if self.cache:
            self.cached[key] = {"signature": signature, "incident_id": result["incident_id"]}
            self.cache.write_text(json.dumps(self.cached, indent=2), encoding="utf-8")
        return self.submitted[key]

    def private_copy(self, incident_id: str, overrides: dict[str, Any] | None = None) -> str:
        """ a new incident row with the submitted one's facts and the case's overrides; the submitted row is never edited """

        overrides = overrides or {}
        incidents = IncidentRepository()
        record = incidents.get(UUID(incident_id))
        fields = dict(record.normalized_fields)
        fields["confidences"] = {**(fields.get("confidences") or {}), **(overrides.get("extraction_overrides") or {})}
        fields |= dict.fromkeys(overrides.get("field_removals") or [])
        fields |= overrides.get("value_overrides") or {}
        copy = incidents.create(record.establishment, fields, record.narrative, owner_analyst_id=self.analyst_id,
                                photo_verdicts=record.photo_verdicts)
        # the copy stands for the same packet submitted again, so it carries the submit's screening result
        submitted = RunRepository().latest(UUID(incident_id), ("submit",))
        if submitted:
            RunRepository().create(uuid4(), "submit", incident_id=copy, escalation_triggers=submitted.get("escalation_triggers"))
        return str(copy)

    def resolve(self, case: dict[str, Any]) -> str | None:
        """ the case's own incident: a private copy of its packet's, with the case's setup overrides applied """

        folder = self.packet(case)
        if folder is None:
            return CONTEXT_INCIDENT
        setup = case.get("setup") or {}
        return self.private_copy(self.submit(folder), {key: setup.get(key) for key in
                                                       ("extraction_overrides", "field_removals", "value_overrides")})


def _signature(folder: Path) -> list:
    """ what a packet is made of: each file's name, size and modification time """

    return sorted([path.name, path.stat().st_size, int(path.stat().st_mtime)] for path in folder.iterdir() if path.is_file())


def _text(run: TurnRun) -> str:
    """ everything the analyst reads from the turn: the answer, every dossier rationale, and the disclosure the CLI
        prints after every command """

    legs = (run.dossier or {}).values()
    parts = [run.answer or ""] + [(leg.get("proposal") or {}).get("rationale", "") for leg in legs]
    if DISCLOSURE not in parts[0]:
        parts.append(DISCLOSURE)
    return "\n".join(parts)


def _sources(run: TurnRun) -> list[dict]:
    found = [{"doc_id": s.doc_id, "section_path": s.section_path, "text": ""} for s in run.sources]
    for leg in (run.dossier or {}).values():
        found += [{"doc_id": hit.get("doc_id", ""), "section_path": hit.get("section_path", ""), "text": hit.get("text", "")}
                  for hit in (leg.get("cited") or {}).values()]
    return found


def _decisions(record: dict | None) -> dict[str, dict]:
    """ the latest decision per rule in a run record """

    items = ((record or {}).get("rule_invocations") or {}).get("items") or []
    return {item["decision"]["rule_id"]: item["decision"] for item in items}


def check_turn(expected: dict[str, Any], run: TurnRun, record: dict | None, earlier: list[dict | None],
               queue_before: Any, queue_after: Any, result: TurnResult) -> None:
    """ every expectation this runner knows, as passed or failed; the rest listed as unchecked """

    ok, bad = result.passed.append, result.failed.append
    result.text = _text(run)
    result.route = run.route
    result.sources = sorted({f"{s['doc_id']} {s['section_path']}" for s in _sources(run)})
    text = result.text.lower()
    refused = run.refusal is not None or run.retrieval_refusal is not None
    result.refused = refused if run.command == "ask" else None

    outcome = expected.get("outcome")
    if outcome in REFUSING:
        (ok if refused else bad)(f"refused (expected a refusal, got {'one' if refused else 'an answer'})")
        want = REFUSALS.get((expected.get("refusal") or {}).get("reason_code"), (expected.get("refusal") or {}).get("reason_code"))
        got = run.retrieval_refusal or (run.refusal or {}).get("reason")
        if want:
            (ok if got == want else bad)(f"refusal reason {got} (expected {want})")
    elif outcome in ANSWERING or expected.get("must_not_refuse"):
        (ok if not refused else bad)(f"answered (refusal: {run.retrieval_refusal or (run.refusal or {}).get('reason')})")

    for phrase in expected.get("must_not_include") or []:
        (bad if phrase.lower() in text else ok)(f'never says "{phrase}"')

    found = _sources(run)
    for source in expected.get("sources") or []:
        hit = any(s["doc_id"] == source["doc_id"] and (not source.get("section_path") or
                  s["section_path"].startswith(str(source["section_path"]))) for s in found)
        (ok if hit else bad)(f"cites {source['doc_id']} {source.get('section_path', '')}".rstrip())

    decisions = _decisions(record)
    for rule in expected.get("rule_outcomes") or []:
        decision = decisions.get(rule["rule_id"])
        label = f"{rule['rule_id']} -> {rule['outcome']}"
        if decision is None:
            bad(f"{label} (not invoked this turn)")
            continue
        problems = [] if decision["outcome"] == rule["outcome"] else [f"got {decision['outcome']}"]
        if "day_count" in rule and decision.get("day_count") != rule["day_count"]:
            problems.append(f"day count {decision.get('day_count')}, expected {rule['day_count']}")
        if "missing_field" in rule and decision.get("missing_field") != rule["missing_field"]:
            problems.append(f"missing field {decision.get('missing_field')}, expected {rule['missing_field']}")
        for key, value in (rule.get("inputs_include") or {}).items():
            if (decision.get("inputs") or {}).get(key) != value:
                problems.append(f"input {key}={(decision.get('inputs') or {}).get(key)}, expected {value}")
        (bad if problems else ok)(f"{label}{' (' + '; '.join(problems) + ')' if problems else ''}")

    if expected.get("rules_engine_invocation_required"):
        (ok if decisions else bad)("a rules-engine invocation was recorded this turn")

    dispatched = set(((record or {}).get("workers_dispatched") or {}).get("items") or [])
    if "workers_dispatched" in expected:
        want = set(expected["workers_dispatched"] or [])
        (ok if dispatched == want else bad)(f"dispatched {sorted(dispatched)} (expected {sorted(want)})")
    for worker in expected.get("workers_not_dispatched") or []:
        (bad if worker in dispatched else ok)(f"did not dispatch {worker}")

    fired = set(run.escalation.fired) if run.escalation else set()
    for trigger in expected.get("escalation_triggers_fired") or []:
        name = TRIGGER_NAMES.get(trigger, trigger)
        (ok if name in fired else bad)(f"{name} fired")
    for trigger in expected.get("escalation_triggers_not_fired") or []:
        name = TRIGGER_NAMES.get(trigger, trigger)
        (bad if name in fired else ok)(f"{name} held")
    if "escalated_to_review_queue" in expected:
        escalated = bool(run.escalation and run.escalation.requires_review)
        (ok if escalated == expected["escalated_to_review_queue"] else bad)(f"escalated: {escalated}")

    if expected.get("reuses_rule_invocation_from_turn"):
        rule = expected.get("reused_rule_id")
        first = _decisions(earlier[expected["reuses_rule_invocation_from_turn"] - 1]).get(rule) if earlier else None
        now = decisions.get(rule)
        same = first is not None and now is not None and (first["outcome"], first.get("inputs")) == (now["outcome"], now.get("inputs"))
        (ok if same else bad)(f"{rule} matches turn {expected['reuses_rule_invocation_from_turn']}'s invocation")

    if "writes_performed" in expected or expected.get("review_queue_row_unchanged"):
        (ok if queue_before == queue_after else bad)("the review queue row is unchanged")

    statements = expected.get("answer_must_include") or []
    if statements:
        for verdict in judge.statements(_text(run), statements):
            result.judged.append(verdict.model_dump())
            (ok if verdict.present == "yes" else bad)(f'states "{verdict.statement}" ({verdict.present})')

    result.unchecked += sorted(key for key in expected if key not in CHECKED)


def chunk_text(chunk_id: str) -> str:
    """ a corpus chunk's text as the Knowledge Base indexed it: kb/corpus/<doc_id>/<chunk_id>.txt in the packet bucket """

    from ..aws import clients
    from ..aws.s3 import BUCKET_NAME
    from ..ingest.corpus.indexing import KB_FOLDER

    key = f"{KB_FOLDER}/{chunk_id.rsplit('-', 1)[0]}/{chunk_id}.txt"
    return clients.s3().get_object(Bucket=BUCKET_NAME, Key=key)["Body"].read().decode("utf-8")


def ground(run: TurnRun, result: TurnResult) -> None:
    """ the groundedness evaluator over every cited claim the analyst reads: the answer's and each dossier leg's """

    if run.answer and run.sources:
        _ground(run.answer, [source.chunk_id for source in run.sources], {}, result)
    for leg in (run.dossier or {}).values():
        proposal = leg.get("proposal") or {}
        _ground(proposal.get("rationale", ""), proposal.get("chunk_ids") or [], leg.get("cited") or {}, result)


def _ground(text: str, chunk_ids: list[str], cited: dict, result: TurnResult) -> None:
    for claim, numbers in judge.cited_claims(text):
        for number in numbers:
            if not 1 <= number <= len(chunk_ids):
                result.grounded.append({"claim": claim, "chunk_id": None, "verdict": "not_supported",
                                        "reason": f"[{number}] resolves to no cited chunk"})
                continue
            chunk_id = chunk_ids[number - 1]
            body = (cited.get(chunk_id) or {}).get("text") or chunk_text(chunk_id)
            verdict = judge.groundedness(claim, body)
            result.grounded.append({"claim": claim, "chunk_id": chunk_id, **(verdict.model_dump() if verdict else
                                    {"verdict": "unjudged", "reason": judge.UNJUDGED})})


def run_case(case: dict[str, Any], incidents: Incidents, *, variant: dict | None = None, judge_grounding: bool = True,
             incident_id: str | None = None) -> LiveResult:
    """ one case's turns in one session; a variant replaces the case's expectations with its own

        incident_id is the case's incident when the caller already resolved it (the parallel runner does, up front)
    """

    live = LiveResult(case["id"], case.get("category", ""), variant and variant.get("name"))
    if incident_id is None:
        try:
            incident_id = incidents.resolve(case)
        except Exception as error:  # noqa: BLE001 - a packet that won't submit fails its case, never the whole run
            live.error = f"setup: {type(error).__name__}: {error}"
            return live

    records: list[dict | None] = []
    for turn in turns(case):
        command = turn["command"]
        expected = (variant or {}).get("expected") or turn.get("expected") or case.get("expected") or {}
        start = time.monotonic()
        result = TurnResult(command, 0.0, 0.0, None)
        live.turns.append(result)
        try:
            if command == "submit":
                # submitted during setup; the case keeps its own copy, unless the turn sends a different packet
                folder = ROOT / turn["path"]
                if incidents.packet(case) is None or folder.resolve() != incidents.packet(case).resolve():
                    incident_id = incidents.private_copy(incidents.submit(folder))
                result.unchecked = sorted(expected)
                records.append(None)
                continue
            if command == "queue":
                listed = [str(row.incident_id) for row in wiring.review_queue(incidents.analyst_id)]
                (result.passed if incident_id in listed else result.failed).append("the incident is in the review queue")
                records.append(None)
                continue
            raw = {"command": command, "incident_id": incident_id, "question": turn.get("query")}
            raw = {key: value for key, value in raw.items() if value is not None}
            queue_before = wiring.pending_review(incident_id, analyst_id=incidents.analyst_id) if incident_id else None
            # the session's spend is kept in Postgres across commands; this turn's is what it added
            session = thread_id(incidents.analyst_id, incident_id, "coordinator")
            spent = Decimal(str(SessionRepository().session_cost(session)))
            run = wiring.turn(raw, analyst_id=incidents.analyst_id)
            record = wiring.latest_run(incident_id, analyst_id=incidents.analyst_id, commands=(command,)) if incident_id else None
            queue_after = wiring.pending_review(incident_id, analyst_id=incidents.analyst_id) if incident_id else None
            result.cost_usd = float(run.usage.cost_usd - spent) if run.usage else 0.0
            check_turn(expected, run, record, records, _snapshot(queue_before), _snapshot(queue_after), result)
            if judge_grounding:
                ground(run, result)
            records.append(record)
        except Exception as error:  # noqa: BLE001 - a failing turn is recorded and its case stops; the run goes on
            result.error = f"{type(error).__name__}: {error}"
            break
        finally:
            result.seconds = round(time.monotonic() - start, 1)
    return live


def _snapshot(review: Any) -> Any:
    return review.model_dump(mode="json") if hasattr(review, "model_dump") else review
