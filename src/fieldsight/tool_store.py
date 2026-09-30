"""Entitlement policy for both Gateway read tools; every query is in the repository module."""

from __future__ import annotations

import logging
from typing import Any

from fieldsight.errors import ToolDenied
from fieldsight.repository import GatewayReadRepository
from fieldsight.schemas.incidents import SimilarCandidate
from fieldsight.security.entitlement import require_grant

logger = logging.getLogger(__name__)


class GatewayReadStore:
    def __init__(self, repository: GatewayReadRepository | None = None) -> None:
        self.repository = repository or GatewayReadRepository()
        self.engine = self.repository.engine

    def _bound_incident(self, email: str, thread_id: str) -> tuple[dict[str, Any], Any]:
        session = self.repository.bound_session(email, thread_id)
        if session is None:
            raise ToolDenied("not_entitled", "No session is bound to this caller")
        incident = require_grant(session["analyst_id"], session["incident_id"], repository=self.repository)
        logger.info("gateway read authorized")
        return incident, session["analyst_id"]

    def extraction(self, verified_email: str, thread_id: str) -> dict[str, Any]:
        incident, _ = self._bound_incident(verified_email, thread_id)
        return {"incident_id": str(incident["incident_id"]), "normalized_fields": incident["normalized_fields"]}

    def similar(self, verified_email: str, thread_id: str, limit: int) -> list[SimilarCandidate]:
        incident, analyst_id = self._bound_incident(verified_email, thread_id)
        if incident["embedding"] is None:
            raise ToolDenied("insufficient_data", "The bound incident has no narrative embedding")
        rows = self.repository.similar_incidents(incident["incident_id"], incident["embedding"], analyst_id, limit)
        return [
            SimilarCandidate(
                incident_id=row["incident_id"], outcome=row["outcome"],
                deciding_rule=row["deciding_rule"],
                similarity_score=max(0.0, min(1.0, 1.0 - float(row["distance"]))),
                matching_narrative_span=(row["narrative"] or "")[:300],
            )
            for row in rows
        ]
