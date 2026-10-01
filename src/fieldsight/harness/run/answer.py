""" the answer_from_retrieval route: a policy question answered from the corpus, through stage 4 """

from collections.abc import Callable

from ...schemas.incidents import NormalizedIncident
from ...schemas.retrieval import DraftAnswer, GroundedAnswer
from ...schemas.run_records import RuleInvocation
from ..guardrails.answer_guard import guard_answer

# the retrieval chain: (question, the guard's objections) -> a grounded answer, or a refusal naming the escalation path
Answerer = Callable[[str, list[str]], GroundedAnswer]


def answer_question(question: str, answerer: Answerer, *, incident: NormalizedIncident | None,
                    rule_invocations: list[RuleInvocation], correlation_id: str) -> dict:
    """ returns the answer safe to show (or a refusal), its sources, this turn's rule invocations, and the events;
        a retrieval refusal is already an answer, so it skips the guard """

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
        latest = grounded[-1]
        retrieved.update(chunk for retrieval in latest.retrievals for chunk in retrieval.scores)
        return DraftAnswer(answer=latest.answer, grounded=latest.grounded, chunk_ids=[source.chunk_id for source in latest.sources])

    guarded = guard_answer(generate, incident=incident, retrieved=retrieved, rule_invocations=rule_invocations,
                           names=set(), correlation_id=correlation_id)
    return {"answer": guarded["text"], "sources": grounded[-1].sources if guarded["text"] else [],
            "refusal": guarded["refusal"], "retrieval_refusal": None, "rule_invocations": guarded["rule_invocations"],
            "events": guarded["events"]}
