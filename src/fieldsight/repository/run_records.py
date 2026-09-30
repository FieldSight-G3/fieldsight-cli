"""Run records: append-only, one per turn; a correction is a new record referencing the original."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import insert, select

from fieldsight.security.redaction import redact_payload, redact_text

from .base import _Repository


class RunRecordRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    correlation_id: UUID
    incident_id: UUID | None
    command: str
    workers_dispatched: dict[str, Any] | None
    tool_invocations: dict[str, Any] | None
    rule_invocations: dict[str, Any] | None
    escalation_triggers: dict[str, Any] | None
    model_calls: dict[str, Any] | None
    reviewer_verdicts: dict[str, Any] | None
    created_at: datetime

class RunRecordRepository(_Repository):
    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("run_records", dsn)

    def create(
        self,
        correlation_id: UUID,
        command: str,
        incident_id: UUID | None = None,
        workers_dispatched: dict[str, Any] | None = None,
        tool_invocations: dict[str, Any] | None = None,
        rule_invocations: dict[str, Any] | None = None,
        escalation_triggers: dict[str, Any] | None = None,
        model_calls: dict[str, Any] | None = None
    ) -> UUID:
        statement = insert(self.table).values(
            correlation_id=correlation_id,
            command=command,
            incident_id=incident_id,
            workers_dispatched=workers_dispatched,
            tool_invocations=tool_invocations,
            rule_invocations=rule_invocations,
            escalation_triggers=escalation_triggers,
            model_calls=model_calls
        ).returning(self.table.c.run_id)
        with self.engine.begin() as connection:
            return connection.execute(statement).scalar_one()

    def get(self, run_id: UUID) -> RunRecordRecord | None:
        return self._get("run_id", run_id, RunRecordRecord)

    def latest(self, incident_id: UUID, commands: tuple[str, ...] = ("analyze", "ask")) -> dict[str, Any] | None:
        """The incident's most recent run record of those commands, with every column the table has, or None."""
        statement = (
            select(self.table)
            .where(self.table.c.incident_id == incident_id, self.table.c.command.in_(commands))
            .order_by(self.table.c.created_at.desc())
            .limit(1)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return dict(row) if row is not None else None

    def record_correction(
        self,
        original_run_id: UUID,
        reason: str,
        correlation_id: UUID,
        *,
        workers_dispatched: dict[str, Any] | None = None,
        tool_invocations: dict[str, Any] | None = None,
        rule_invocations: dict[str, Any] | None = None,
        escalation_triggers: dict[str, Any] | None = None,
        model_calls: dict[str, Any] | None = None
    ) -> UUID:
        """A new, PII-redacted record that references the run it corrects; the original row is never edited."""
        if not reason.strip():
            raise ValueError("A correction needs a reason")
        with self.engine.begin() as connection:
            original = connection.execute(
                select(self.table.c.incident_id).where(self.table.c.run_id == original_run_id)
            ).one_or_none()
            if original is None:
                raise LookupError(f"Run {original_run_id} does not exist")
            return connection.execute(
                insert(self.table).values(
                    correlation_id=correlation_id,
                    command="correction",
                    incident_id=original.incident_id,
                    corrects_run_id=original_run_id,
                    correction_reason=redact_text(reason, "correction_reason"),
                    workers_dispatched=redact_payload(workers_dispatched),
                    tool_invocations=redact_payload(tool_invocations),
                    rule_invocations=redact_payload(rule_invocations),
                    escalation_triggers=redact_payload(escalation_triggers),
                    model_calls=redact_payload(model_calls)
                ).returning(self.table.c.run_id)
            ).scalar_one()

    def corrections_of(self, run_id: UUID) -> list[dict[str, Any]]:
        """Every correction recorded against a run, oldest first."""
        statement = (
            select(self.table.c.run_id, self.table.c.correction_reason, self.table.c.created_at)
            .where(self.table.c.corrects_run_id == run_id)
            .order_by(self.table.c.created_at, self.table.c.run_id)
        )
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings().all()]
