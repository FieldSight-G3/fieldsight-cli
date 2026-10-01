""" the answer_from_retrieval route: a policy question answered from the corpus, through stage 4 """

from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage

from ...aws import clients
from ...prompts import PROMPTS
from ...schemas.incidents import NormalizedIncident
from ...schemas.retrieval import DraftAnswer, GroundedAnswer
from ...schemas.run_records import RuleInvocation
from ..guardrails.answer_guard import guard_answer


class _Refused(Exception):
    """ a regeneration came back a retrieval refusal; it ends the guard's loop and becomes the turn's answer """

    def __init__(self, answer: GroundedAnswer) -> None:
        super().__init__(answer.refusal_reason)
        self.answer = answer


# the retrieval chain: (question, the guard's objections) -> a grounded answer, or a refusal naming the escalation path
Answerer = Callable[[str, list[str]], GroundedAnswer]


def question_facts(question: str, incident_id: str) -> NormalizedIncident | None:
    """ the facts a policy question states about the case it describes, as an incident the rules can run over

        A policy question is about the case it describes, never the open incident, so a threshold its answer states
        is attributed to the rules run over these facts. A field the question doesn't state is null; a stated one is
        the analyst's own words, so it's read at full confidence. None when the question states no facts at all.
    """

    model = clients.chat_model(fast=True).with_structured_output(NormalizedIncident)
    read = model.invoke([SystemMessage(PROMPTS["question_facts"]), HumanMessage(question)])
    if read is None:
        return None
    values = read.model_dump(exclude={"incident_id", "confidences", "sources"})
    # an empty treatment list is the model filling a field, never a question saying no treatment was given
    if not values.get("treatments"):
        values["treatments"] = None
    stated = {name: 1.0 for name, value in values.items() if value is not None}
    if not stated:
        return None
    return NormalizedIncident(incident_id=incident_id, **values, confidences=stated, sources={})


def answer_question(question: str, answerer: Answerer, *, incident: NormalizedIncident | None,
                    rule_invocations: list[RuleInvocation], correlation_id: str, about_incident: bool = False) -> dict:
    """ returns the answer safe to show (or a refusal), its sources, this turn's rule invocations, and the events;
        a retrieval refusal is already an answer, so it skips the guard

        incident is the open one; a threshold in the answer is attributed to the facts the question states, read
        only if the answer states one, never to the open incident's. about_incident is a follow-up on the incident's
        own analysis: its thresholds are attributed to the incident, and rule_invocations already carry what that
        analysis recorded, so nothing is decided again.
    """

    grounded = [answerer(question, [])]
    if grounded[0].refusal_reason:
        # the refusal text is the answer the analyst reads; the reason is kept so the turn can be told apart from one
        return {"answer": grounded[0].answer, "sources": [], "refusal": None, "retrieval_refusal": grounded[0].refusal_reason,
                "rule_invocations": rule_invocations, "events": []}

    # every chunk retrieved this turn, across regenerations; guard_answer reads it after each draft
    retrieved: set[str] = set()

    def generate(objections: list[str]) -> DraftAnswer:
        if objections:
            grounded.append(answerer(question, objections))
            if grounded[-1].refusal_reason:
                # the retry couldn't ground an answer: that refusal is the honest result, not a draft to cite
                raise _Refused(grounded[-1])
        latest = grounded[-1]
        retrieved.update(chunk for retrieval in latest.retrievals for chunk in retrieval.scores)
        return DraftAnswer(answer=latest.answer, grounded=latest.grounded, chunk_ids=[source.chunk_id for source in latest.sources])

    incident_id = incident.incident_id if incident else "question"
    try:
        subject = incident if about_incident else (lambda: question_facts(question, incident_id))
        guarded = guard_answer(generate, incident=subject, retrieved=retrieved,
                               rule_invocations=rule_invocations, names=set(), correlation_id=correlation_id)
    except _Refused as refused:
        return {"answer": refused.answer.answer, "sources": [], "refusal": None,
                "retrieval_refusal": refused.answer.refusal_reason, "rule_invocations": rule_invocations, "events": []}
    return {"answer": guarded["text"], "sources": grounded[-1].sources if guarded["text"] else [],
            "refusal": guarded["refusal"], "retrieval_refusal": None, "rule_invocations": guarded["rule_invocations"],
            "events": guarded["events"]}
