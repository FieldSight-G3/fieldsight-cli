""" defining the tools for the specialists to use; each reads its subject from the injected graph state, never from an argument """

import json
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ..errors import RetrievalError, RuleError
from ..retrieval.corpus import meta, search
from ..rules import proposal_review
from ..rules.engine import evaluate_rule as run_rule
from ..schemas.rule_proposal import ClassificationProposal, ReportingProposal

# the rules each specialist may run
HELD_RULES = {"recordability": {"R1", "R3", "R4"}, "reportability": {"R2"}}


def respond(result: dict, tool_call_id: str, **state_update) -> Command:
    """ answer the model with the result and record what the tool found in the specialist's state """

    return Command(update={**state_update, "messages": [ToolMessage(json.dumps(result), tool_call_id=tool_call_id)]})


def latest_decisions(state: dict) -> dict[str, dict]:
    """ the latest decision per rule this run """

    return {decision["rule_id"]: decision for decision in state["decisions"]}


@tool
def get_incident_extraction(state: Annotated[dict, InjectedState]) -> dict:
    """ The normalized facts extracted from this incident's packet, and each field's extraction confidence.

        A field is null when it couldn't be read. Call this first: every rule runs over these facts.
    """

    return {"fields": {key: value for key, value in state["incident"].items() if key != "incident_id"}}


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
    results = [
        {**{key: meta(doc)[key] for key in ("chunk_id", "doc_id", "title", "doc_type", "section_path")},
         "score": doc.metadata["score"], "text": doc.page_content}
        for doc in docs]
    return respond({"results": results}, tool_call_id, retrieved=[hit["chunk_id"] for hit in results])


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

    held = HELD_RULES[state["worker"]]
    if rule_id not in held:
        return {"error": f"this specialist holds {', '.join(sorted(held))}"}
    try:
        decision = run_rule(rule_id, state["incident"], latest_decisions(state))
    except RuleError as error:
        return {"error": str(error)}
    return respond({"decision": decision}, tool_call_id, decisions=[decision])


def propose(proposal: ClassificationProposal | ReportingProposal, problems: list[str], tool_call_id: str) -> Command:
    """ the verdict goes back to the model; an accepted proposal also goes into state, which ends the loop """

    if problems:
        return respond({"status": "rejected", "problems": problems}, tool_call_id)
    accepted = proposal.model_dump(mode="json")
    return respond({"status": "accepted", "proposal": accepted}, tool_call_id, proposal=accepted)


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

    problems = proposal_review.review_classification(proposal, latest_decisions(state), set(state["retrieved"]))
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

    problems = proposal_review.review_reporting(proposal, latest_decisions(state), set(state["retrieved"]))
    return propose(proposal, problems, tool_call_id)


# creating lists of the tools to BIND to each specialist's model
RECORDABILITY_TOOLS = [get_incident_extraction, search_knowledge_base, evaluate_rule, propose_classification]
REPORTABILITY_TOOLS = [get_incident_extraction, search_knowledge_base, evaluate_rule, propose_reporting_determination]
