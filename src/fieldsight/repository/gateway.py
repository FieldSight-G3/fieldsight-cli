"""The queries behind the two Gateway read tools; the entitlement policy stays in tool_store."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import MetaData, Table, select

from .base import _Repository


class GatewayReadRepository(_Repository):
    """Queries behind the two Gateway read tools; the entitlement policy stays in tool_store."""

    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("incidents", dsn)
        metadata = MetaData()
        self.sessions = Table("sessions", metadata, autoload_with=self.engine)
        self.analysts = Table("analysts", metadata, autoload_with=self.engine)
        self.grants = Table("grants", metadata, autoload_with=self.engine)

    def bound_session(self, email: str, thread_id: str) -> dict[str, Any] | None:
        statement = (
            select(self.sessions.c.analyst_id, self.sessions.c.incident_id)
            .join(self.analysts, self.analysts.c.analyst_id == self.sessions.c.analyst_id)
            .where(self.sessions.c.thread_id == thread_id, self.analysts.c.email == email)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return dict(row) if row is not None else None

    def tool_incident(self, incident_id: UUID) -> dict[str, Any] | None:
        statement = (
            select(self.table.c.incident_id, self.table.c.establishment, self.table.c.normalized_fields,
                   self.table.c.embedding, self.table.c.narrative)
            .where(self.table.c.incident_id == incident_id)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return dict(row) if row is not None else None

    def has_grant(self, analyst_id: UUID, establishment: str) -> bool:
        statement = (
            select(self.grants.c.grant_id)
            .where(self.grants.c.analyst_id == analyst_id, self.grants.c.establishment == establishment)
            .limit(1)
        )
        with self.engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none() is not None

    def similar_incidents(self, incident_id: UUID, embedding: Any, analyst_id: UUID, limit: int) -> list[dict[str, Any]]:
        """Closed incidents nearest the embedding, only from establishments the analyst is granted."""
        distance = self.table.c.embedding.cosine_distance(embedding)
        statement = (
            select(self.table.c.incident_id, self.table.c.outcome, self.table.c.deciding_rule,
                   self.table.c.narrative, distance.label("distance"))
            .join(self.grants, (self.grants.c.establishment == self.table.c.establishment) & (self.grants.c.analyst_id == analyst_id))
            .where(self.table.c.incident_id != incident_id, self.table.c.embedding.is_not(None),
                   self.table.c.outcome.is_not(None), self.table.c.deciding_rule.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings().all()]
