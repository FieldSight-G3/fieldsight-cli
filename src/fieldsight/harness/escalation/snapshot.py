""" the dossier as submitted, frozen onto the review queue row when a turn escalates, and the citations it carries """

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CitationReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)


class ReviewSnapshot(BaseModel):
    """The dossier as submitted, frozen onto the review queue row if the case escalates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    submitting_analyst_id: UUID
    dossier: dict[str, Any]
    citations: dict[str, CitationReference]

    @classmethod
    def of(cls, submitting_analyst_id: UUID | str, dossier: dict[str, Any] | None) -> "ReviewSnapshot":
        """The dossier the Reviewer saw, with every cited chunk mapped to its source document, keyed by chunk id.

        An empty dossier is valid: a case routed straight to a human still records who submitted it.
        """
        dossier = dict(dossier or {})
        citations = {
            chunk_id: CitationReference(document_id=hit["doc_id"], chunk_id=chunk_id)
            for leg in dossier.values()
            for chunk_id, hit in (leg.get("cited") or {}).items()
        }
        return cls(submitting_analyst_id=UUID(str(submitting_analyst_id)), dossier=dossier, citations=citations)
