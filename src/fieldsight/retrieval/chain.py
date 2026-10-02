""" RAG chain: gather evidence, answer only from it, check citations """

from operator import itemgetter
from typing import Any, cast

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import (
    Runnable,
    RunnableBranch,
    RunnableLambda,
    RunnablePassthrough,
)

from ..aws import clients
from ..schemas.retrieval import DraftAnswer
from .corpus import meta
from .evidence import gather
from .grounding import enforce_grounding, refuse

GROUNDED_SYSTEM = """You are answering questions about OSHA recordkeeping from a
corpus of federal regulatory text.

The excerpts below are the ONLY source you may use. They override anything you
believe about OSHA rules.

- If the excerpts answer the question, answer from them. Cite every sentence as [n],
  where n is the position of the excerpt's chunk id in your chunk_ids list.
- Don't restate the question's facts in a sentence of their own; apply the regulation
  to them in a cited sentence instead.
- If the excerpts do NOT cover the question, set grounded to false and say what is
  missing. Do not fill the gap from general knowledge.
- Describe what the regulation says. Never state whether this employer must record
  or report; the analyst determines that.
- When the question states a case's facts, say which side of the provision those facts
  fall on, naming the outcome plainly (recordable, reportable, a log column), e.g. "loss
  of an eye is reportable under 1904.39(a)(2) [n]". The system checks each such outcome
  against its rules engine and attributes it to the rule that decides it. That sentence
  cites the provision it applies, like every other sentence. Its subject is the kind of
  injury or event ("an injury involving loss of consciousness"), never "the case", "this
  case", "the incident" or "the injury", which read as deciding this employer's case.
- When you give values from a table, also state any footnote or condition in the
  excerpt that limits when those values apply.
- The preamble explains the rule and the comments OSHA received, including proposals
  the final rule changed. Where it differs from the regulatory text, follow the
  regulatory text.
- State an obligation as what the provision requires, e.g. "1904.39(a)(1) requires
  employers to report a fatality within 8 hours", never as "must be reported", "must
  be recorded" or "you must", which read as a determination. Paraphrase a provision's
  "must" sentence this way; don't quote it.
- When an excerpt from a letter of interpretation or the directive addresses the
  question's specific situation, it applies the general rule to that situation: lead
  with what it says, then the general rule it applies.

Excerpts:
{context}"""


def format_docs(docs: list[Document]) -> str:
    """ chunks as blocks the model can cite by chunk id """

    return "\n\n".join(
        f"--- chunk_id: {meta(doc)['chunk_id']} | {meta(doc)['doc_id']} {meta(doc)['section_path']} "
        f"| {meta(doc)['title']}, p. {meta(doc)['page']} ---\n{doc.page_content.strip()}"
        for doc in docs)


def build_rag_chain() -> Runnable:
    """ {"question": ...} -> GroundedAnswer; skips the model when nothing clears the threshold """

    # a regeneration's objections go in the system message: in the human turn, "your previous answer was refused,
    # fix these" reads as an injection to the Bedrock Prompt Attacks filter, which blocks the whole call
    prompt = ChatPromptTemplate.from_messages([
        ("system", GROUNDED_SYSTEM + "{objections}"),
        ("human", "{question}")
    ]).partial(objections="")

    structured_model: Runnable[Any, DraftAnswer] = cast(
        "Runnable[Any, DraftAnswer]",
        clients.chat_model().with_structured_output(DraftAnswer)
    )

    answer = (
        RunnablePassthrough.assign(context=itemgetter("docs") | RunnableLambda(format_docs))
        | RunnablePassthrough.assign(draft=prompt | structured_model)
        | RunnableLambda(enforce_grounding)
    )

    return RunnableLambda(gather) | RunnableBranch(
        (lambda evidence: evidence["refusal"] is None, answer),
        RunnableLambda(refuse),
    )
