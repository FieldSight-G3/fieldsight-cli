"""Apply a human review to one pending queue item.

The request carries only the reviewer's action. The caller supplies an identity
verified by the session layer; the store supplies the original, immutable
dossier and the submitting analyst. Persistence must be atomic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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


class ReviewStore(Protocol):
    def get_pending(self, queue_id: UUID) -> PendingReview | None: ...

    def record_if_pending(self, decision: ReviewDecision) -> bool:
        """Atomically save the decision and status only while status is pending."""
        ...


def submit_review(request: ReviewRequest, *, queue_id: UUID, verified_reviewer_id: UUID, store: ReviewStore, source_for_chunk: ChunkSource | None = None, decided_at: datetime | None = None) -> ReviewDecision:
    """Validate, then save one human decision using the trusted review context."""
    pending = store.get_pending(queue_id)
    if pending is None:
        raise ReviewConflict("Queue item is missing or no longer pending")

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
