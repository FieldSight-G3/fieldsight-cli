""" a pending review as the reviewer reads it back: the queue row's trusted metadata and its frozen snapshot """

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .snapshot import CitationReference


class PendingReview(BaseModel):
    """Trusted queue metadata and a snapshot captured when the case was queued."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_id: UUID
    incident_id: UUID
    submitting_analyst_id: UUID
    original_payload: dict[str, Any]
    original_citations: dict[str, CitationReference]
