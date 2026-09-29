from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fieldsight.types.corpus import DocType

RefusalReason = Literal["below_threshold", "retrieval_unavailable", "not_grounded", "unresolved_citation"]


class Hop(BaseModel):
    """A second search a chunk's cross-reference calls for."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="Text to send to the Knowledge Base")
    doc_type: DocType = Field(description="doc_type filter for the search")
    section_path: str | None = Field(default=None, description="section_path filter, when the hop targets one section")
    reason: str = Field(description="The chunk whose cross-reference this hop follows")


class Retrieval(BaseModel):
    """One Knowledge Base search in the chain, as the run record keeps it."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="Text sent to the Knowledge Base")
    doc_type: DocType | None = Field(default=None, description="doc_type filter, when the search was narrowed")
    section_path: str | None = Field(default=None, description="section_path filter, when the search was narrowed")
    reason: str = Field(description="Why this search ran: the question itself, or the chunk whose cross-reference it follows")
    scores: dict[str, float] = Field(description="Every chunk id returned above the threshold, with its similarity score")
    superseded: bool = Field(
        default=False,
        description="A filtered search that found nothing and was retried across the whole corpus"
    )


class Citation(BaseModel):
    """One entry of a grounded answer's sources array, resolved against the retrieved chunks."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    title: str
    section_path: str
    chunk_id: str


class DraftAnswer(BaseModel):
    """What the model returns from the corpus excerpts, before its citations are checked."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(
        description="The answer, citing each claim as [n], where n is the position of the chunk in chunk_ids, starting at 1"
    )
    grounded: bool = Field(
        description="False when the excerpts do not answer the question"
    )
    chunk_ids: list[str] = Field(
        description="The chunk ids of the excerpts cited, in the order [n] refers to them"
    )


class GroundedAnswer(BaseModel):
    """A corpus answer whose citations all resolve, or a refusal naming what was searched and where to escalate."""

    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str = Field(description="The cited answer, or the refusal as the analyst reads it")
    grounded: bool
    sources: list[Citation] = Field(
        default_factory=list,
        description="Resolved citations; [n] in the answer is sources[n - 1]"
    )
    refusal_reason: RefusalReason | None = None
    searched: list[str] = Field(default_factory=list, description="What was searched for, in words")
    escalation: str | None = Field(default=None, description="Where to take the question when it is refused")
    below_threshold_anywhere: bool = Field(
        default=False,
        description="Some search in the chain found nothing above the similarity threshold"
    )
    retrievals: list[Retrieval] = Field(default_factory=list)
