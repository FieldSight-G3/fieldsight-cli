"""Parameterized, read-only SQLAlchemy queries used by both Gateway tools."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import MetaData, Table, and_, select

from fieldsight.repository import IncidentRepository
from fieldsight.tool_service import SimilarCandidate, ToolDenied

logger = logging.getLogger(__name__)


class GatewayReadStore:
    def __init__(self, repository: IncidentRepository | None = None) -> None:
        repository = repository or IncidentRepository()
        self.engine = repository.engine
        metadata = MetaData()
        self.incidents = repository.table
        self.sessions = Table("sessions", metadata, autoload_with=self.engine)
        self.analysts = Table("analysts", metadata, autoload_with=self.engine)
        self.grants = Table("grants", metadata, autoload_with=self.engine)

    def _bound_incident(self, connection: Any, email: str, thread_id: str) -> Any:
        session = connection.execute(
            select(self.sessions.c.analyst_id, self.sessions.c.incident_id)
            .join(self.analysts, self.analysts.c.analyst_id == self.sessions.c.analyst_id)
            .where(and_(self.sessions.c.thread_id == thread_id, self.analysts.c.email == email))
        ).mappings().one_or_none()
        if session is None:
            raise ToolDenied("not_entitled", "No session is bound to this caller")
        incident = connection.execute(
            select(self.incidents.c.incident_id, self.incidents.c.establishment, self.incidents.c.normalized_fields,
                   self.incidents.c.embedding, self.incidents.c.narrative)
            .where(self.incidents.c.incident_id == session["incident_id"])
        ).mappings().one_or_none()
        if incident is None:
            raise ToolDenied("not_found", "The bound incident is unavailable")
        grant = connection.execute(
            select(self.grants.c.grant_id)
            .where(and_(self.grants.c.analyst_id == session["analyst_id"],
                        self.grants.c.establishment == incident["establishment"]))
            .limit(1)
        ).scalar_one_or_none()
        if grant is None:
            raise ToolDenied("not_entitled", "Caller has no grant for this establishment")
        logger.info("gateway read authorized")
        return incident, session["analyst_id"]

    def extraction(self, verified_email: str, thread_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            incident, _ = self._bound_incident(connection, verified_email, thread_id)
            return {"incident_id": str(incident["incident_id"]), "normalized_fields": incident["normalized_fields"]}

    def similar(self, verified_email: str, thread_id: str, limit: int) -> list[SimilarCandidate]:
        with self.engine.connect() as connection:
            incident, analyst_id = self._bound_incident(connection, verified_email, thread_id)
            if incident["embedding"] is None:
                raise ToolDenied("insufficient_data", "The bound incident has no narrative embedding")
            distance = self.incidents.c.embedding.cosine_distance(incident["embedding"])
            rows = connection.execute(
                select(self.incidents.c.incident_id, self.incidents.c.outcome,
                       self.incidents.c.deciding_rule, self.incidents.c.narrative,
                       distance.label("distance"))
                .join(self.grants, and_(self.grants.c.establishment == self.incidents.c.establishment,
                                        self.grants.c.analyst_id == analyst_id))
                .where(and_(self.incidents.c.incident_id != incident["incident_id"],
                            self.incidents.c.embedding.is_not(None),
                            self.incidents.c.outcome.is_not(None),
                            self.incidents.c.deciding_rule.is_not(None)))
                .order_by(distance)
                .limit(limit)
            ).mappings().all()
        return [
            SimilarCandidate(
                incident_id=row["incident_id"], outcome=row["outcome"],
                deciding_rule=row["deciding_rule"],
                similarity_score=max(0.0, min(1.0, 1.0 - float(row["distance"]))),
                matching_narrative_span=(row["narrative"] or "")[:300],
            )
            for row in rows
        ]
