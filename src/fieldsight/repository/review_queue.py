"""The review queue: pending items, their frozen dossiers, and one recorded human decision per item."""

from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import MetaData, Table, insert, or_, select, update
from sqlalchemy.exc import OperationalError

from fieldsight.harness.bounds import BoundsConfig
from fieldsight.harness.escalation.pending import PendingReview
from fieldsight.harness.escalation.review import (
    CitationReference,
    ReviewConflict,
    ReviewDecision,
    ReviewWriteFailed,
)

from .base import _Repository


class ReviewQueueRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queue_id: UUID
    incident_id: UUID
    triggers: dict[str, Any]
    status: str
    decision: dict[str, Any] | None
    created_at: datetime

class ReviewQueueRepository(_Repository):
    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("review_queue", dsn)
        # the write after approval closes the incident in the decision's transaction
        self.incidents = Table("incidents", MetaData(), autoload_with=self.engine)

    def create(self, incident_id: UUID, triggers: dict[str, Any]) -> UUID:
        statement = insert(self.table).values(
            incident_id=incident_id,
            triggers=triggers
        ).returning(self.table.c.queue_id)
        with self.engine.begin() as connection:
            return connection.execute(statement).scalar_one()

    def get(self, queue_id: UUID) -> ReviewQueueRecord | None:
        return self._get("queue_id", queue_id, ReviewQueueRecord)

    def list_pending(self, reviewer_id: UUID | None = None) -> list[ReviewQueueRecord]:
        """Every pending item, oldest first; with a reviewer, only those over an establishment they hold a grant for."""
        columns = [self.table.c[name] for name in ReviewQueueRecord.model_fields]
        statement = select(*columns).where(self.table.c.status == "pending").order_by(self.table.c.created_at)
        if reviewer_id is not None:
            metadata = MetaData()
            incidents = Table("incidents", metadata, autoload_with=self.engine)
            grants = Table("grants", metadata, autoload_with=self.engine)
            statement = (
                statement.join(incidents, incidents.c.incident_id == self.table.c.incident_id)
                .join(grants, grants.c.establishment == incidents.c.establishment)
                .where(grants.c.analyst_id == reviewer_id)
            )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [ReviewQueueRecord.model_validate(dict(row)) for row in rows]

    def pending_queue_id(self, incident_id: UUID) -> UUID | None:
        """The queue id of the incident's oldest pending review, or None when it has none."""
        statement = (
            select(self.table.c.queue_id)
            .where(self.table.c.incident_id == incident_id, self.table.c.status == "pending")
            .order_by(self.table.c.created_at)
            .limit(1)
        )
        with self.engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none()

    def pending_for_incident(self, incident_id: UUID) -> PendingReview | None:
        """The incident's oldest pending review with its snapshot, or None when it has none."""
        queue_id = self.pending_queue_id(incident_id)
        return self.get_pending(queue_id) if queue_id is not None else None

    def get_pending(self, queue_id: UUID) -> PendingReview | None:
        columns = [self.table.c[name] for name in ("queue_id", "incident_id", "submitting_analyst_id", "dossier_snapshot", "citations")]
        statement = select(*columns).where(self.table.c.queue_id == queue_id, self.table.c.status == "pending")
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        if row is None or row["submitting_analyst_id"] is None or row["dossier_snapshot"] is None or row["citations"] is None:
            return None
        citations = {key: CitationReference.model_validate(value) for key, value in row["citations"].items()}
        return PendingReview(queue_id=row["queue_id"], incident_id=row["incident_id"], submitting_analyst_id=row["submitting_analyst_id"], original_payload=row["dossier_snapshot"], original_citations=citations)

    def reviewer_entitled(self, reviewer_id: UUID, incident_id: UUID) -> bool:
        metadata = MetaData()
        incidents = Table("incidents", metadata, autoload_with=self.engine)
        grants = Table("grants", metadata, autoload_with=self.engine)
        statement = (
            select(grants.c.grant_id)
            .join(incidents, incidents.c.establishment == grants.c.establishment)
            .where(incidents.c.incident_id == incident_id, grants.c.analyst_id == reviewer_id)
            .limit(1)
        )
        with self.engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none() is not None

    def record_if_pending(self, decision: ReviewDecision, *, execution_key: UUID | None = None,
                          limits: BoundsConfig | None = None) -> bool:
        """Record the decision only while the item is pending. An approval with an execution key also runs the write
        after approval in the same transaction: the incident is closed under that key, and a retry with the same key
        applies once. An incident already closed under another key is a conflict, and the decision isn't recorded."""
        limits = limits or BoundsConfig.from_environment()
        payload = decision.model_dump(mode="json")
        statement = (
            update(self.table)
            .where(self.table.c.queue_id == decision.queue_id, self.table.c.incident_id == decision.incident_id, self.table.c.status == "pending")
            .values(status=decision.status, decision=payload, reviewer_id=decision.reviewer_id, decided_at=decision.decided_at)
            .returning(self.table.c.queue_id)
        )
        recorded = select(self.table.c.decision).where(self.table.c.queue_id == decision.queue_id)
        incidents = self.incidents
        execute = (
            update(incidents)
            .where(incidents.c.incident_id == decision.incident_id,
                   or_(incidents.c.execution_key.is_(None), incidents.c.execution_key == execution_key))
            .values(status="closed", execution_key=execution_key)
            .returning(incidents.c.incident_id)
        )
        for attempt in range(limits.db_write_max_attempts):
            try:
                with self.engine.begin() as connection:
                    # a dropped connection can hide a commit; the same decision already stored is a success, not a conflict
                    if attempt and connection.execute(recorded).scalar_one_or_none() == payload:
                        return True
                    if connection.execute(statement).scalar_one_or_none() is None:
                        return False
                    executes = decision.status == "approved" and execution_key is not None
                    if executes and connection.execute(execute).scalar_one_or_none() is None:
                        # raising inside the transaction rolls the decision back with it
                        raise ReviewConflict(f"Incident {decision.incident_id} was already closed by another approval")
                    return True
            except OperationalError as error:
                if attempt + 1 == limits.db_write_max_attempts:
                    raise ReviewWriteFailed(f"Review decision not saved after {limits.db_write_max_attempts} attempts") from error
                time.sleep(limits.db_write_backoff_seconds * 2 ** attempt * (1 + random.random()))
        raise AssertionError("unreachable")
