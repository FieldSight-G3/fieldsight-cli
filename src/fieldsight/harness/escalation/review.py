"""Validate and apply a human review to one pending queue item.

decide_review checks the reviewer's action without writing. submit_review
builds the trusted context from the store and a verified identity, then saves
the decision atomically. The request carries only the reviewer's action; the
store supplies the original, immutable dossier and the submitting analyst.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fieldsight.errors import FieldSightError
from fieldsight.logging_context import with_correlation_id

# determination-shaped phrases a narrative edit may reword around but never introduce or change
_DETERMINATION = re.compile(
    r"\b(?:not[\s_-]+)?(?:recordable|reportable)\b"
    r"|\bcolumn[\s_-]*[ghij]\b"
    r"|\b(?P<amount>\d+(?:\.\d+)?)[\s-]*(?P<unit>hours?|hrs?|h|days?|d)\b"
    r"|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    re.IGNORECASE,
)


def _determinations(text: str) -> set[str]:
    found = set()
    for match in _DETERMINATION.finditer(text):
        if match["unit"]:
            unit = "days" if match["unit"].lower().startswith("d") else "hours"
            found.add(f"{match['amount']} {unit}")
        elif match.group()[0].isdigit():
            found.add(match.group())
        else:
            found.add(" ".join(re.split(r"[\s_-]+", match.group().lower())))
    return found


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def introduced_determinations(original_payload: Mapping[str, Any], narrative: str) -> set[str]:
    """Outcomes, periods and dates the edited narrative states that the original dossier never did."""
    original = set().union(*(_determinations(text) for text in _strings(dict(original_payload))))
    return _determinations(narrative) - original


ReviewAction = Literal["approve", "edit_then_approve", "reject"]
ChunkSource = Callable[[str], str | None]


class CitationReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)


class CitationRepoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_id: str = Field(min_length=1)
    replacement_chunk_id: str = Field(min_length=1)


class ReviewEdit(BaseModel):
    """Only the narrative, note, and same-document citation may change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    narrative: str | None = None
    note: str | None = None
    citation_repoints: list[CitationRepoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def has_edit(self) -> ReviewEdit:
        if self.narrative is None and self.note is None and not self.citation_repoints:
            raise ValueError("Edit then approve requires a narrative, note, or citation repoint")
        return self


class ReviewRequest(BaseModel):
    """The reviewer supplies the action; identity comes from the trusted session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: ReviewAction
    edit: ReviewEdit | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def valid_action(self) -> ReviewRequest:
        if (self.action == "edit_then_approve") != (self.edit is not None):
            raise ValueError("Only edit_then_approve accepts an edit, and it requires one")
        if self.action == "reject" and not (self.reason and self.reason.strip()):
            raise ValueError("Reject requires a reason")
        return self


class ReviewContext(BaseModel):
    """Values supplied by the harness, not filled in by an agent or request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_id: UUID
    incident_id: UUID
    submitting_analyst_id: UUID
    reviewer_id: UUID
    decided_at: datetime

    @model_validator(mode="after")
    def separate_reviewers(self) -> ReviewContext:
        if self.submitting_analyst_id == self.reviewer_id:
            raise ValueError("The submitting analyst cannot review their own dossier")
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ValueError("Review timestamp must have a timezone")
        return self


class ReviewDecision(BaseModel):
    """Payload for review_queue.decision; preserve original and edit separately."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_id: UUID
    incident_id: UUID
    action: ReviewAction
    status: Literal["approved", "rejected"]
    reviewer_id: UUID
    decided_at: datetime
    original_payload: dict[str, Any]
    edit: ReviewEdit | None
    reason: str | None


class PendingReview(BaseModel):
    """Trusted queue metadata and a snapshot captured when the case was queued."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_id: UUID
    incident_id: UUID
    submitting_analyst_id: UUID
    original_payload: dict[str, Any]
    original_citations: dict[str, CitationReference]


class ReviewConflict(FieldSightError):
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


def decide_review(request: ReviewRequest, context: ReviewContext, *, original_payload: Mapping[str, Any], original_citations: Mapping[str, CitationReference], source_for_chunk: ChunkSource | None = None) -> ReviewDecision:
    """Check a human action and return a persistable decision without writing."""
    if request.edit is not None and request.edit.narrative is not None:
        introduced = introduced_determinations(original_payload, request.edit.narrative)
        if introduced:
            raise ValueError(f"An edit may reword but not change a determination ({', '.join(sorted(introduced))}); reject instead")
    if request.edit is not None:
        seen: set[str] = set()
        for repoint in request.edit.citation_repoints:
            if repoint.citation_id in seen:
                raise ValueError(f"Citation {repoint.citation_id} was repointed twice")
            seen.add(repoint.citation_id)
            original = original_citations.get(repoint.citation_id)
            if original is None:
                raise ValueError(f"Citation {repoint.citation_id} is not in the original dossier")
            if repoint.replacement_chunk_id == original.chunk_id:
                raise ValueError("Replacement must point to a different chunk")
            if source_for_chunk is None or source_for_chunk(repoint.replacement_chunk_id) != original.document_id:
                raise ValueError("Replacement chunk must resolve to the same document")

    return ReviewDecision(
        queue_id=context.queue_id,
        incident_id=context.incident_id,
        action=request.action,
        status="rejected" if request.action == "reject" else "approved",
        reviewer_id=context.reviewer_id,
        decided_at=context.decided_at,
        original_payload=deepcopy(dict(original_payload)),
        edit=request.edit,
        reason=request.reason,
    )


@with_correlation_id
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
