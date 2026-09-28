"""Apply a human review to one pending queue item.

The request carries only the reviewer's action. The caller supplies an identity
verified by the session layer; the store supplies the original, immutable
dossier and the submitting analyst. Persistence must be atomic.
"""


import re
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from fieldsight.errors import FieldSightError
from fieldsight.review_decisions import (
    ChunkSource,
    CitationReference,
    ReviewContext,
    ReviewDecision,
    ReviewRequest,
    decide_review,
)


class PendingReview(BaseModel):
    """Trusted queue metadata and a snapshot captured when the case was queued."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_id: UUID
    incident_id: UUID
    submitting_analyst_id: UUID
    original_payload: dict[str, Any]
    original_citations: dict[str, CitationReference]


class ReviewConflict(Exception):
    """The queue item is missing or has already received a decision."""


class ReviewNotEntitled(FieldSightError):
    """The reviewer holds no grant over the incident's establishment."""


class ReviewWriteFailed(FieldSightError):
    """The decision could not be saved after every bounded retry."""


# corpus chunk ids are "{doc_id}-{12 hex digits}" (ingest/corpus/chunking.py chunk_id)
_CHUNK_ID = re.compile(r"(?P<document_id>.+)-[0-9a-f]{12}\Z")


def document_for_chunk(chunk_id: str) -> str | None:
    """The source document a corpus chunk id belongs to, or None if it isn't a corpus chunk id."""
    match = _CHUNK_ID.fullmatch(chunk_id)
    return match["document_id"] if match else None


class ReviewStore(Protocol):
    def get_pending(self, queue_id: UUID) -> PendingReview | None: ...

    def reviewer_entitled(self, reviewer_id: UUID, incident_id: UUID) -> bool:
        """True only if the reviewer holds a grant over the incident's establishment."""
        ...

    def record_if_pending(self, decision: ReviewDecision) -> bool:
        """Atomically save the decision and status only while status is pending."""
        ...


def submit_review(request: ReviewRequest, *, queue_id: UUID, verified_reviewer_id: UUID, store: ReviewStore, source_for_chunk: ChunkSource | None = None, decided_at: datetime | None = None) -> ReviewDecision:
    """Validate, then save one human decision using the trusted review context."""
    pending = store.get_pending(queue_id)
    if pending is None:
        raise ReviewConflict("Queue item is missing or no longer pending")
    # entitlement runs on every call, not once per session
    if not store.reviewer_entitled(verified_reviewer_id, pending.incident_id):
        raise ReviewNotEntitled("Reviewer has no grant for this incident's establishment")

    context = ReviewContext(
        queue_id=pending.queue_id,
        incident_id=pending.incident_id,
        submitting_analyst_id=pending.submitting_analyst_id,
        reviewer_id=verified_reviewer_id,
        decided_at=decided_at if decided_at is not None else datetime.now(UTC),
    )
    decision = decide_review(
        request,
        context,
        original_payload=pending.original_payload,
        original_citations=pending.original_citations,
        source_for_chunk=source_for_chunk,
    )
    if not store.record_if_pending(decision):
        raise ReviewConflict("Queue item received another decision")
    return decision
