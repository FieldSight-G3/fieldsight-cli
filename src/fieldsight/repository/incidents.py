"""Incident rows and one turn's writes: the outcome, the run record and the review queue row in one transaction."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import MetaData, Table, insert, select, update

from fieldsight.harness.escalation.review import CitationReference

from .base import _Repository


class IncidentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: UUID
    establishment: str
    submitted_at: datetime
    normalized_fields: dict[str, Any]
    narrative: str | None
    outcome: dict[str, Any] | None
    deciding_rule: str | None
    status: str
    photo_verdicts: dict[str, Any] | None

class IncidentRepository(_Repository):
    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("incidents", dsn)

    def create(self, establishment: str, normalized_fields: dict[str, Any], narrative: str | None = None, owner_analyst_id: UUID | None = None, photo_verdicts: dict[str, Any] | None = None) -> UUID:
        statement = insert(self.table).values(
            establishment=establishment,
            normalized_fields=normalized_fields,
            narrative=narrative,
            owner_analyst_id=owner_analyst_id,
            photo_verdicts=photo_verdicts
        ).returning(self.table.c.incident_id)
        with self.engine.begin() as connection:
            return connection.execute(statement).scalar_one()

    def get(self, incident_id: UUID) -> IncidentRecord | None:
        return self._get("incident_id", incident_id, IncidentRecord)

    def save_analysis(self, incident_id: UUID, correlation_id: UUID, outcome: dict[str, Any] | None, deciding_rule: str | None, rule_invocations: list[dict[str, Any]], escalation_triggers: dict[str, Any] | None, *, requires_review: bool, command: str = "analyze", workers_dispatched: dict[str, Any] | None = None,
                      tool_invocations: dict[str, Any] | None = None, model_calls: dict[str, Any] | None = None,
                      reviewer_verdicts: dict[str, Any] | None = None, dossier: dict[str, Any] | None = None) -> UUID:
        """One turn's writes in one transaction; outcome is None for a turn that must not overwrite it, like ask."""
        metadata = MetaData()
        run_records = Table("run_records", metadata, autoload_with=self.engine)
        review_queue = Table("review_queue", metadata, autoload_with=self.engine) if requires_review else None
        with self.engine.begin() as connection:
            if outcome is not None:
                updated = connection.execute(
                    update(self.table)
                    .where(self.table.c.incident_id == incident_id)
                    .values(outcome=outcome, deciding_rule=deciding_rule)
                    .returning(self.table.c.incident_id)
                ).scalar_one_or_none()
                if updated is None:
                    raise LookupError(f"Incident {incident_id} does not exist")
            run_id = connection.execute(
                insert(run_records)
                .values(
                    correlation_id=correlation_id,
                    incident_id=incident_id,
                    command=command,
                    workers_dispatched=workers_dispatched,
                    rule_invocations={"items": rule_invocations},
                    escalation_triggers=escalation_triggers,
                    tool_invocations=tool_invocations,
                    model_calls=model_calls,
                    reviewer_verdicts=reviewer_verdicts,
                    dossier=dossier,
                )
                .returning(run_records.c.run_id)
            ).scalar_one()
            if review_queue is not None:
                connection.execute(
                    insert(review_queue).values(
                        incident_id=incident_id,
                        triggers=escalation_triggers,
                    )
                )
        return run_id

    def save_analysis_for_review(self, incident_id: UUID, correlation_id: UUID, outcome: dict[str, Any] | None, deciding_rule: str | None, rule_invocations: list[dict[str, Any]], escalation_triggers: dict[str, Any], *, submitting_analyst_id: UUID, dossier_snapshot: dict[str, Any], citations: dict[str, CitationReference], command: str = "analyze", workers_dispatched: dict[str, Any] | None = None, tool_invocations: dict[str, Any] | None = None, model_calls: dict[str, Any] | None = None, reviewer_verdicts: dict[str, Any] | None = None, dossier: dict[str, Any] | None = None) -> UUID:
        """Like save_analysis with requires_review, but queues an immutable dossier snapshot for get_pending; outcome is None for a turn that must not overwrite it, like ask."""
        metadata = MetaData()
        run_records = Table("run_records", metadata, autoload_with=self.engine)
        review_queue = Table("review_queue", metadata, autoload_with=self.engine)
        with self.engine.begin() as connection:
            exists = connection.execute(
                select(self.table.c.incident_id).where(self.table.c.incident_id == incident_id)
            ).scalar_one_or_none()
            if exists is None:
                raise LookupError(f"Incident {incident_id} does not exist")
            if outcome is not None:
                connection.execute(
                    update(self.table)
                    .where(self.table.c.incident_id == incident_id)
                    .values(outcome=outcome, deciding_rule=deciding_rule)
                )
            run_id = connection.execute(
                insert(run_records)
                .values(
                    correlation_id=correlation_id,
                    incident_id=incident_id,
                    command=command,
                    workers_dispatched=workers_dispatched,
                    rule_invocations={"items": rule_invocations},
                    escalation_triggers=escalation_triggers,
                    tool_invocations=tool_invocations,
                    model_calls=model_calls,
                    reviewer_verdicts=reviewer_verdicts,
                    dossier=dossier,
                )
                .returning(run_records.c.run_id)
            ).scalar_one()
            connection.execute(
                insert(review_queue).values(
                    incident_id=incident_id,
                    triggers=escalation_triggers,
                    submitting_analyst_id=submitting_analyst_id,
                    dossier_snapshot=dossier_snapshot,
                    citations={key: value.model_dump(mode="json") for key, value in citations.items()}
                )
            )
        return run_id
