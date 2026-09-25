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

- If the excerpts answer the question, answer from them. Cite every claim as [n],
  where n is the position of the excerpt's chunk id in your chunk_ids list.
- If the excerpts do NOT cover the question, set grounded to false and say what is
  missing. Do not fill the gap from general knowledge.
- Describe what the regulation says. Never state whether this employer must record
  or report; the analyst determines that.

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

    prompt = ChatPromptTemplate.from_messages([
        ("system", GROUNDED_SYSTEM),
        ("human", "{question}")
    ])

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
