""" defining the tools for the specialists to use; each reads its subject from the injected graph state, never from an argument """

import json
import re
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel

from ..aws.gateway_reads import GATEWAY_UNAVAILABLE
from ..errors import RetrievalError, RuleError
from ..harness.guardrails.common import DETERMINATION
from ..retrieval.corpus import meta, provision_text, search
from ..rules import proposal_review
from ..rules.engine import evaluate_rule as run_rule
from ..schemas.review import ReviewVerdict
from ..schemas.rule_proposal import (
    ClassificationProposal,
    HazardControlProposal,
    ReportingProposal,
)

TOOLSETS: dict[str, list]


def respond(result: dict, tool_call_id: str, **state_update) -> Command:
    """ answer the model with the result and record what the tool found in the specialist's state """

    return Command(update={**state_update, "messages": [ToolMessage(json.dumps(result), tool_call_id=tool_call_id)]})


@tool
def get_incident_extraction(state: Annotated[dict, InjectedState]) -> dict:
    """ The normalized facts extracted from this incident's packet, and each field's extraction confidence.

        A field is null when it couldn't be read. Call this first: every rule runs over these facts.
    """

    gateway = state.get("gateway")
    if gateway is None:
        # no Gateway configured (local development): the harness's own copy of the same record
        return {"fields": {key: value for key, value in state["incident"].items() if key != "incident_id"}}
    # read through the AgentCore Gateway as the analyst at turn start (aws/gateway_reads)
    if gateway.get("extraction") is None:
        return {"unavailable": gateway["unavailable"].get("get_incident_extraction", GATEWAY_UNAVAILABLE)}
    fields = gateway["extraction"]["normalized_fields"]
    return {"fields": {key: value for key, value in fields.items() if key != "incident_id"}}


@tool
def find_similar_incidents(state: Annotated[dict, InjectedState]) -> dict:
    """ Closed incidents most like this one, from establishments the analyst may see: each one's outcome, deciding
        rule, similarity score and narrative. Optional precedent only; it never decides a control.
    """

    gateway = state.get("gateway")
    if gateway is None:
        return {"unavailable": "find_similar_incidents is read through the AgentCore Gateway, which isn't configured"}
    if gateway.get("similar") is None:
        return {"unavailable": gateway["unavailable"].get("find_similar_incidents", GATEWAY_UNAVAILABLE)}
    return {"items": gateway["similar"]}


@tool(parse_docstring=True)
def search_knowledge_base(
    query: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    doc_type: str | None = None,
    section_path: str | None = None,
) -> Command | dict:
    """ Search the regulatory corpus for the provisions a finding rests on.

    Returns chunks above the similarity threshold, best first, each with the chunk_id to cite.
    Call it again to follow a cross-reference or to check an exclusion. An empty result means
    nothing in the corpus matched well enough: rephrase or widen the filter rather than guess.

    Args:
        query: What to look for, in plain words.
        doc_type: Narrow to one layer: regulation, directive, preamble, interpretation or form.
        section_path: Narrow to one section, e.g. 1904.39, or a letter of interpretation's date, e.g. 2021-01-08.
    """

    try:
        docs = search(query, doc_type=doc_type, section_path=section_path)
    except RetrievalError as error:
        return {"error": str(error)}
    results = [hit_of(doc) for doc in docs]
    # keep each hit, not just its id, so the Reviewer can judge a claim against the text it cites
    return respond({"results": results}, tool_call_id, retrieved={hit["chunk_id"]: hit for hit in results})


def hit_of(doc) -> dict:
    """ a retrieved chunk as a tool returns it and the worker's state keeps it """

    found = {key: meta(doc)[key] for key in ("chunk_id", "doc_id", "title", "doc_type", "section_path")}
    return {**found, "paragraph": meta(doc).get("paragraph", found["section_path"]),
            "score": doc.metadata["score"], "text": doc.page_content}


@tool(parse_docstring=True)
def read_provision(
    provisions: list[str],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command | dict:
    """ Read regulation provisions by their citations, all in one call, e.g. every provision your rule decisions list.

    Returns, for each provision, the chunks that state it, each with the chunk_id to cite. A sentence restating a
    rule decision cites one of the chunks for a provision in that decision's sources.

    Args:
        provisions: The provisions as rule decisions' sources name them, e.g. ["29 CFR 1904.7(b)(5)(ii)", "29 CFR 1904.4(a)"].
    """

    by_provision, retrieved = {}, {}
    for provision in dict.fromkeys(provisions):
        try:
            # an exact lookup by paragraph, not a similarity search: its hits carry no score, so they never count as
            # retrieval falling below the threshold
            hits = [{key: value for key, value in hit_of(doc).items() if key != "score"} for doc in provision_text(provision)]
        except RetrievalError as error:
            return {"error": str(error)}
        by_provision[provision] = hits or "no regulation chunk states it; cite the closest one your searches found"
        retrieved |= {hit["chunk_id"]: hit for hit in hits}
    return respond({"provisions": by_provision}, tool_call_id, retrieved=retrieved)


@tool(parse_docstring=True)
def evaluate_rule(
    rule_id: str,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command | dict:
    """ Run a deterministic rule over this incident's extracted facts.

    The rule, not you, decides every threshold outcome. insufficient_data names the missing field.
    R1 uses R3's decision and R4 uses R1's, so evaluate them in that order.

    Args:
        rule_id: R3 medical treatment beyond first aid, R1 recordability, R4 the 300-Log column, R2 the reporting clock.
    """

    try:
        decision = run_rule(rule_id, state["incident"], state["decisions"])
    except RuleError as error:
        return {"error": str(error)}
    return respond({"decision": decision}, tool_call_id, decisions={decision["rule_id"]: decision})


@tool(parse_docstring=True)
def evaluate_rules(
    rule_ids: list[str],
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command | dict:
    """ Run several deterministic rules over this incident's extracted facts, in the order given, in one call.

    Each rule sees the decisions of the rules before it, so ["R3", "R1", "R4"] runs R1 on R3's decision and R4 on
    R1's. The rules, not you, decide every threshold outcome. insufficient_data names the missing field.

    Args:
        rule_ids: rules in order. R3 medical treatment beyond first aid, R1 recordability, R4 the 300-Log column, R2 the reporting clock.
    """

    # one round instead of one per rule: a worker's tool rounds are capped, and the proposal needs the ones left
    decisions = dict(state["decisions"])
    results: dict[str, dict] = {}
    for rule_id in rule_ids:
        try:
            decision = run_rule(rule_id, state["incident"], decisions)
        except RuleError as error:
            results[rule_id] = {"error": str(error)}
            continue
        decisions[decision["rule_id"]] = results[rule_id] = decision
    return respond({"decisions": results}, tool_call_id,
                   decisions={rule_id: decision for rule_id, decision in results.items() if "error" not in decision})


def propose(proposal: BaseModel, problems: list[str], tool_call_id: str) -> Command:
    """ the verdict goes back to the model; an accepted proposal also goes into state, which ends the loop

        A rationale that states a determination is refused here, where the worker can still rephrase it, rather
        than at stage 4, which would withhold the whole leg (the same check, harness/guardrails/dossier_guard).
    """

    if determination := DETERMINATION.search(getattr(proposal, "rationale", "") or ""):
        problems = [*problems, (f'"{determination.group()}" states a determination. Attribute the outcome to the rule '
                                f'that decided it instead, e.g. "R1 found the 1904.7 recording criteria met" or "R2 found '
                                f'the event reportable under 1904.39(a)(2)", and avoid "must", "is recordable" and '
                                f'"is reportable" anywhere in the rationale')]
    if problems:
        return respond({"status": "rejected", "problems": problems}, tool_call_id)
    accepted = proposal.model_dump(mode="json")
    return respond({"status": "accepted", "proposal": accepted}, tool_call_id, proposal=accepted)


# a citation written as the chunk id itself, e.g. [CFR-1904-d6bf67b0d2f6] or [CFR-1904-..., CPL-172-...]
CHUNK_ID = r"[A-Z][A-Z0-9-]*-[0-9a-f]{12}"
CITED_BY_ID = re.compile(rf"\[\s*({CHUNK_ID}(?:\s*,\s*{CHUNK_ID})*)\s*\]")


def numbered(proposal: BaseModel, retrieved: dict) -> BaseModel:
    """ the proposal with each citation by chunk id rewritten as its [n] position in chunk_ids

        Workers sometimes cite [CFR-1904-d6bf67b0d2f6] instead of [1]. The checks only read [n], so a correct citation
        was rejected over its format until the worker ran out of rounds. A cited id retrieved this run but missing
        from chunk_ids is added; one never retrieved is left as written, so the checks still catch it.
    """

    rationale = getattr(proposal, "rationale", None)
    if not rationale or not CITED_BY_ID.search(rationale):
        return proposal
    chunk_ids = list(proposal.chunk_ids)

    def position(match: re.Match) -> str:
        ids = [chunk_id.strip() for chunk_id in match.group(1).split(",")]
        if not all(chunk_id in chunk_ids or chunk_id in retrieved for chunk_id in ids):
            return match.group(0)
        for chunk_id in ids:
            if chunk_id not in chunk_ids:
                chunk_ids.append(chunk_id)
        return "".join(f"[{chunk_ids.index(chunk_id) + 1}]" for chunk_id in ids)

    return proposal.model_copy(update={"rationale": CITED_BY_ID.sub(position, rationale), "chunk_ids": chunk_ids})


@tool(parse_docstring=True)
def propose_classification(
    proposal: ClassificationProposal,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """ Propose the recordability finding. Writes nothing.

    Checked against this run's R1 and R4 decisions and the chunks retrieved this run.
    Returns accepted, or the problems to fix before proposing again.

    Args:
        proposal: The outcome, column and day count exactly as the rules returned them, a rationale, and its chunk ids.
    """

    proposal = numbered(proposal, state["retrieved"])
    problems = proposal_review.review_classification(proposal, state["decisions"], set(state["retrieved"]))
    problems += proposal_review.rule_citation_problems(proposal, state["decisions"], state["retrieved"])
    return propose(proposal, problems, tool_call_id)


@tool(parse_docstring=True)
def propose_reporting_determination(
    proposal: ReportingProposal,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """ Propose the reporting finding. Writes nothing.

    Checked against this run's R2 decision, including any exclusion it applied, and the chunks
    retrieved this run. Returns accepted, or the problems to fix before proposing again.

    Args:
        proposal: The outcome, clock, deadline and exclusion exactly as R2 returned them, a rationale, and its chunk ids.
    """

    proposal = numbered(proposal, state["retrieved"])
    problems = proposal_review.review_reporting(proposal, state["decisions"], set(state["retrieved"]))
    problems += proposal_review.rule_citation_problems(proposal, state["decisions"], state["retrieved"])
    return propose(proposal, problems, tool_call_id)


@tool(parse_docstring=True)
def propose_hazard_control(
    proposal: HazardControlProposal,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """ Propose the control 29 CFR 1910.269(l) requires here. Writes nothing.

    A proposed control needs its control type and the specific paragraph (l) provision or
    approach-distance table it rests on, carried by the first chunk id, a 1910.269 chunk
    retrieved this run. Where the corpus supports no control, propose insufficient_data.
    Returns accepted, or the problems to fix before proposing again.

    Args:
        proposal: The outcome, control type, provision, a rationale, its chunk ids with the provision's chunk first, and any precedents.
    """

    proposal = numbered(proposal, state["retrieved"])
    problems = proposal_review.review_hazard_control(proposal, set(state["retrieved"]))
    found = {item["incident_id"] for item in (state.get("gateway") or {}).get("similar") or []}
    problems += [f"precedent {precedent} wasn't returned by find_similar_incidents this run"
                 for precedent in map(str, proposal.precedents) if precedent not in found]
    return propose(proposal, problems, tool_call_id)


@tool(parse_docstring=True)
def submit_review(
    verdict: ReviewVerdict,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """ Submit your verdict on the dossier. Writes nothing.

    Approve only when every leg is grounded, cited, attributed and descriptive; otherwise
    list one rejection per claim that can't stand, each with a narrowed goal for its worker.

    Args:
        verdict: approved, or the rejections: the worker, the quoted claim, the problem, and the narrowed goal.
    """

    return propose(verdict, [], tool_call_id)


# the tools to BIND to each participant's model (spec section 9)
TOOLSETS = {
    "recordability": [get_incident_extraction, search_knowledge_base, read_provision, evaluate_rule, evaluate_rules,
                      propose_classification],
    "reportability": [get_incident_extraction, search_knowledge_base, read_provision, evaluate_rule,
                      propose_reporting_determination],
    "hazard_control": [search_knowledge_base, find_similar_incidents, propose_hazard_control],
    "reviewer": [search_knowledge_base, submit_review],
}
